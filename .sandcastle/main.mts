// 按角色分配 agent 的四阶段编排。跑法：npm run sandcastle
//
// Plan：读 ready-for-agent 的 issue，建依赖图，输出 <plan> JSON。
// Execute + Review：每个未被阻塞的 issue 各起一个沙箱，implementer 先跑，产出 commit
//   后 reviewer 在同一沙箱同一分支上跑。全部并发。
// Merge：把所有产出分支合回当前分支并关 issue。
//
// 外层循环让上一轮合并后新解锁的 issue 能被接上。

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { z } from "zod";

const requireEnv = (key: string): string => {
  const value = process.env[key];
  if (!value) {
    throw new Error(
      `缺少环境变量 ${key}——请检查 .sandcastle/secrets.env（模板见 secrets.env.example）`,
    );
  }
  return value;
};

// 凭据只下发给 agent，不放进 .sandcastle/.env——那个文件里的每个 key 都会注入每一个
// 沙箱，包括本不需要它的。
const claudeEnv = () => ({
  CLAUDE_CODE_OAUTH_TOKEN: requireEnv("CLAUDE_CODE_OAUTH_TOKEN"),
});

// sandcastle 只在 `docker run` 那一刻注入 env，此后一律 `docker exec` 不带 -e；而
// createSandbox() 把 agentProviderEnv 写死成了 {}。所以光给 claudeCode 传 env 不够，
// 走 createSandbox 的 implementer/reviewer 会拿不到凭据、以 "Not logged in" 退出。
// 这里把 env 拼成 `KEY=v claude ...` 的命令前缀一起送进去。
// POSIX sh 的单引号内无转义，碰到 ' 只能先闭合、拼一个转义过的单引号、再开。
const shQuote = (value: string) => `'${value.replaceAll("'", `'\\''`)}'`;

const withInlineEnv = <T extends sandcastle.AgentProvider>(
  agent: T,
  env: Record<string, string>,
): T => ({
  ...agent,
  buildPrintCommand: (options: sandcastle.AgentCommandOptions) => {
    const inner = agent.buildPrintCommand(options);
    const prefix = Object.entries(env)
      .map(([key, value]) => `${key}=${shQuote(value)}`)
      .join(" ");
    return { ...inner, command: `${prefix} ${inner.command}` };
  },
});

const plannerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() }),
    claudeEnv(),
  );

// captureSessions 关掉：四个角色同为 claudeCode provider，会话会写进同一个 ~/.claude
// 存储，混在一起后 resume/fork 容易接错。
const implementerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("claude-opus-5", {
      env: claudeEnv(),
      captureSessions: false,
    }),
    claudeEnv(),
  );

const reviewerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() }),
    claudeEnv(),
  );

const mergerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() }),
    claudeEnv(),
  );

const planSchema = z.object({
  issues: z.array(
    z.object({ id: z.string(), title: z.string(), branch: z.string() }),
  ),
});

// run() 的重载会把 Output.object 的泛型推成 any，显式标注把类型接回来。
type Plan = z.infer<typeof planSchema>;

const MAX_ITERATIONS = 10;

// 镜像里已有装好 GDAL/pyproj/quarto/pytest 的 conda 环境，这里只把仓库装成可编辑模式
// 让 pytest 能 import moondata。--no-deps：依赖已在镜像里。--no-build-isolation：否则
// pip 会为 requires=["setuptools>=68"] 联网重下一份，实测 40s，打满 hook 的 60s 预算。
const hooks = {
  sandbox: {
    onSandboxReady: [
      { command: "pip install -e . --no-deps --no-build-isolation" },
    ],
  },
};

// 只读是硬要求：那 919 GB 原始影像不可再生。
// MOONDATA_DATA_ROOT 走 provider env，命中 moondata.config 的第二层优先级，所以本机
// 那个 gitignore 掉的 moondata.toml 不用进容器。
const DATA_ROOT_HOST = "G:/Lunar_Optical_SAR_Registration_Dataset";
const DATA_ROOT_SANDBOX = "/mnt/data";

const sandboxProvider = () =>
  docker({
    mounts: [
      { hostPath: DATA_ROOT_HOST, sandboxPath: DATA_ROOT_SANDBOX, readonly: true },
    ],
    env: { MOONDATA_DATA_ROOT: DATA_ROOT_SANDBOX },
  });

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // 阶段 1：Plan
  const plan = await sandcastle.run({
    hooks,
    sandbox: sandboxProvider(),
    name: "planner",
    // 结构化输出要求 maxIterations 为 1；planner 只读不写，一轮够了。
    maxIterations: 1,
    agent: plannerAgent(),
    promptFile: "./.sandcastle/plan-prompt.md",
    output: sandcastle.Output.object({ tag: "plan", schema: planSchema }),
  });

  const issues: Plan["issues"] = plan.output.issues;

  if (issues.length === 0) {
    console.log("没有未被阻塞的 issue，退出。");
    break;
  }

  console.log(`规划完成，${issues.length} 个 issue 可并行：`);
  for (const issue of issues) {
    console.log(`  ${issue.id}: ${issue.title} → ${issue.branch}`);
  }

  // 阶段 2：Execute + Review
  // implementer 和 reviewer 共享一个沙箱，reviewer 看到的就是 implementer 刚提交的
  // 那个分支。allSettled：一个流水线失败不影响其余。
  const settled = await Promise.allSettled(
    issues.map(async (issue) => {
      const sandbox = await sandcastle.createSandbox({
        branch: issue.branch,
        sandbox: sandboxProvider(),
        hooks,
      });

      try {
        const implement = await sandbox.run({
          name: `implementer:${issue.id}`,
          maxIterations: 100,
          agent: implementerAgent(),
          promptFile: "./.sandcastle/implement-prompt.md",
          promptArgs: {
            TASK_ID: issue.id,
            ISSUE_TITLE: issue.title,
            BRANCH: issue.branch,
          },
        });

        if (implement.commits.length > 0) {
          const review = await sandbox.run({
            name: `reviewer:${issue.id}`,
            maxIterations: 1,
            agent: reviewerAgent(),
            promptFile: "./.sandcastle/review-prompt.md",
            promptArgs: { BRANCH: issue.branch },
          });

          // 每次 sandbox.run() 只返回自己那趟的 commit，合并起来给下游看全量。
          return {
            ...review,
            commits: [...implement.commits, ...review.commits],
          };
        }

        return implement;
      } finally {
        await sandbox.close();
      }
    }),
  );

  for (const [i, outcome] of settled.entries()) {
    if (outcome.status === "rejected") {
      console.error(
        `  ✗ ${issues[i]!.id}（${issues[i]!.branch}）失败：${outcome.reason}`,
      );
    }
  }

  const completedIssues = settled
    .map((outcome, i) => ({ outcome, issue: issues[i]! }))
    .filter(
      (entry) =>
        entry.outcome.status === "fulfilled" &&
        entry.outcome.value.commits.length > 0,
    )
    .map((entry) => entry.issue);

  const completedBranches = completedIssues.map((i) => i.branch);

  console.log(`\n执行完成，${completedBranches.length} 个分支有 commit：`);
  for (const branch of completedBranches) {
    console.log(`  ${branch}`);
  }

  if (completedBranches.length === 0) {
    console.log("没有产出 commit，无需合并。");
    continue;
  }

  // 阶段 3：Merge
  await sandcastle.run({
    hooks,
    sandbox: sandboxProvider(),
    name: "merger",
    maxIterations: 1,
    agent: mergerAgent(),
    promptFile: "./.sandcastle/merge-prompt.md",
    promptArgs: {
      BRANCHES: completedBranches.map((b) => `- ${b}`).join("\n"),
      ISSUES: completedIssues.map((i) => `- ${i.id}: ${i.title}`).join("\n"),
    },
  });

  console.log("\n分支已合并。");
}

console.log("\n全部完成。");
