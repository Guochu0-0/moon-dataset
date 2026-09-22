// Parallel Planner with Review —— 按角色分配 agent 的四阶段编排
//
// 阶段 1（Plan）：  读 ready-for-agent 的 issue，建依赖图，输出 <plan> JSON。
// 阶段 2（Execute + Review）：每个未被阻塞的 issue 各起一个沙箱，implementer 先跑，
//                    产出 commit 后 reviewer 在同一沙箱同一分支上跑。全部并发。
// 阶段 3（Merge）：  一个 agent 把所有产出分支合回当前分支并关 issue。
//
// 外层循环最多跑 MAX_ITERATIONS 轮，让上一轮合并后新解锁的 issue 能被接上。
//
// 跑法：npm run sandcastle

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { z } from "zod";

// ---------------------------------------------------------------------------
// 凭据
// ---------------------------------------------------------------------------

const requireEnv = (key: string): string => {
  const value = process.env[key];
  if (!value) {
    throw new Error(
      `缺少环境变量 ${key}——请检查 .sandcastle/secrets.env（模板见 secrets.env.example）`,
    );
  }
  return value;
};

// 两套凭据各自只下发给用到它的 agent，不经 .sandcastle/.env 全量注入沙箱。
const claudeEnv = () => ({
  CLAUDE_CODE_OAUTH_TOKEN: requireEnv("CLAUDE_CODE_OAUTH_TOKEN"),
});
const deepseekEnv = () => ({
  ANTHROPIC_BASE_URL: "https://api.deepseek.com/anthropic",
  ANTHROPIC_AUTH_TOKEN: requireEnv("DEEPSEEK_API_KEY"),
});

// ---------------------------------------------------------------------------
// 按角色分配 agent
//
// 判断依据是「推理深度 vs. 迭代次数」：planner/reviewer/merger 都是单轮、吃推理
// 质量，用订阅（不按 token 计费）；implementer 每个 issue 最多 100 轮、是烧量的
// 大头，用 DeepSeek 按量付费更划算。
// ---------------------------------------------------------------------------

// 规划：依赖分析要判断哪些 issue 会改到重叠文件，错判直接导致合并冲突。
const plannerAgent = () =>
  sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() });

// 实现：跑量最大的一环。用 DeepSeek 最强的 deepseek-v4-pro，走 Anthropic 兼容端点，
// 复用同一个 Claude Code CLI。
// captureSessions 关掉：它和下面几个同为 claudeCode provider，会话会写进同一个
// ~/.claude 存储，混在一起后 resume/fork 容易接错。
const implementerAgent = () =>
  sandcastle.claudeCode("deepseek-v4-pro", {
    env: deepseekEnv(),
    captureSessions: false,
  });

// 审查：要对着 CODING_STANDARDS.md 判断实现是否偏离本仓库约定，不能用便宜模型。
const reviewerAgent = () =>
  sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() });

// 合并：要读两边改动判断冲突怎么解，解错会静默丢代码。
const mergerAgent = () =>
  sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() });

// ---------------------------------------------------------------------------
// 配置
// ---------------------------------------------------------------------------

const planSchema = z.object({
  issues: z.array(
    z.object({ id: z.string(), title: z.string(), branch: z.string() }),
  ),
});

// run() 的重载会把 Output.object 的泛型推成 any，下游就全是隐式 any 了。
// 显式标注 plan.output，把类型接回来。
type Plan = z.infer<typeof planSchema>;

// plan→execute→merge 的最大轮数。
const MAX_ITERATIONS = 10;

// 沙箱就绪后、agent 启动前跑。镜像里已有一个装了 numpy+pytest 的 venv 并挂在 PATH 上
// （见 Dockerfile），这里只把仓库本身装成可编辑模式，让 `pytest` 能 import moondata。
// --no-deps：依赖已在镜像里，避免每次重新解析。
const hooks = {
  sandbox: {
    onSandboxReady: [{ command: "pip install -e . --no-deps" }],
  },
};

// ---------------------------------------------------------------------------
// 主循环
// ---------------------------------------------------------------------------

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);

  // -------------------------------------------------------------------------
  // 阶段 1：Plan
  // -------------------------------------------------------------------------
  const plan = await sandcastle.run({
    hooks,
    sandbox: docker(),
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

  // -------------------------------------------------------------------------
  // 阶段 2：Execute + Review
  //
  // 每个 issue 用 createSandbox() 起一个沙箱，implementer 和 reviewer 共享它，
  // 因此 reviewer 看到的就是 implementer 刚提交的那个分支。
  // allSettled：一个流水线失败不影响其余。
  // -------------------------------------------------------------------------
  const settled = await Promise.allSettled(
    issues.map(async (issue) => {
      const sandbox = await sandcastle.createSandbox({
        branch: issue.branch,
        sandbox: docker(),
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

        // 没有 commit 就没什么可审的。
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

  // 只把真的产出了 commit 的分支交给合并阶段。
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

  // -------------------------------------------------------------------------
  // 阶段 3：Merge
  // -------------------------------------------------------------------------
  await sandcastle.run({
    hooks,
    sandbox: docker(),
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
