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
// 把 agent 的 env 随命令一起送进容器
//
// sandcastle 只在 `docker run` 那一刻注入 env，之后一律是 `docker exec`，不带 -e。
// 而 createSandbox() 建容器时把 agentProviderEnv 写死成了 {}，sandbox.run() 也从不
// 读 provider.env——于是走 createSandbox 的 implementer 和 reviewer 拿不到任何模型
// 凭据，claude 直接以 "Not logged in" 退出。planner/merger 走顶层 sandcastle.run()，
// 容器由它自己创建、env 在 docker run 时注入，所以不受影响。这正是头一次跑
// planner 正常、implementer 全挂的原因。
//
// 这里把 env 拼成 `KEY=v claude ...` 的命令前缀。选它而不是塞进 docker 的 env，是
// 因为 implementer 和 reviewer 共用一个容器却要用两套互斥的凭据：前缀只作用于单条
// 命令，implementer 的 ANTHROPIC_BASE_URL 不会留在容器里把 reviewer 也悄悄改道到
// DeepSeek。
//
// 凭据不会进日志：sandcastle 只记 stdout/stderr 的解析结果，不记命令本身。
// ---------------------------------------------------------------------------

// POSIX sh 的单引号里没有任何转义，所以碰到 ' 只能先闭合、拼一个转义过的单引号、再开。
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

// ---------------------------------------------------------------------------
// 按角色分配 agent
//
// 判断依据是「推理深度 vs. 迭代次数」：planner/reviewer/merger 都是单轮、吃推理
// 质量，用订阅（不按 token 计费）；implementer 每个 issue 最多 100 轮、是烧量的
// 大头，用 DeepSeek 按量付费更划算。
// ---------------------------------------------------------------------------

// 规划：依赖分析要判断哪些 issue 会改到重叠文件，错判直接导致合并冲突。
const plannerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() }),
    claudeEnv(),
  );

// 实现：跑量最大的一环。用 DeepSeek 最强的 deepseek-v4-pro，走 Anthropic 兼容端点，
// 复用同一个 Claude Code CLI。
// captureSessions 关掉：它和下面几个同为 claudeCode provider，会话会写进同一个
// ~/.claude 存储，混在一起后 resume/fork 容易接错。
const implementerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("deepseek-v4-pro", {
      env: deepseekEnv(),
      captureSessions: false,
    }),
    deepseekEnv(),
  );

// 审查：要对着 CODING_STANDARDS.md 判断实现是否偏离本仓库约定，不能用便宜模型。
const reviewerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() }),
    claudeEnv(),
  );

// 合并：要读两边改动判断冲突怎么解，解错会静默丢代码。
const mergerAgent = () =>
  withInlineEnv(
    sandcastle.claudeCode("claude-opus-5", { env: claudeEnv() }),
    claudeEnv(),
  );

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

// 沙箱就绪后、agent 启动前跑。镜像里已有一个装了 GDAL/pyproj/quarto/pytest 的 conda
// 环境并挂在 PATH 上（见 Dockerfile），这里只把仓库本身装成可编辑模式，让 `pytest`
// 能 import moondata。--no-deps：依赖已在镜像里，避免每次重新解析。
const hooks = {
  sandbox: {
    onSandboxReady: [{ command: "pip install -e . --no-deps" }],
  },
};

// ---------------------------------------------------------------------------
// 沙箱
//
// 数据根整份只读挂进去，agent 因此能真的跑完四步流程、并对着 Processed_Data 里的
// 既有产物做逐字节验收。只读是硬要求：那 919 GB 原始影像不可再生。
//
// MOONDATA_DATA_ROOT 走 provider 的 env，命中 moondata.config 的第二层优先级，
// 所以本机那个 gitignore 掉的 moondata.toml 不用进容器。
//
// 性能实测（3000 个小文件 stat）：宿主原生 58k 次/s、容器原生 394k 次/s、
// 经 bind mount 仅 511 次/s。慢 100 倍以上的是小文件元数据，而不是吞吐——
// GDAL 按块随机读影像实测容器反而略快于宿主（64 KB 块 1082 vs 828 次/s）。
// 代价落在全量逐字节验收上：22934 个 patch 跑一遍约 10 分钟。
// 想消掉它只能让数据落在容器原生文件系统上，但 sandcastle 的 mounts 只接受宿主
// 路径、够不着 named volume，而数据在仓库外也 COPY 不进镜像。故暂时接受。
// ---------------------------------------------------------------------------

const DATA_ROOT_HOST = "G:/Lunar_Optical_SAR_Registration_Dataset";
const DATA_ROOT_SANDBOX = "/mnt/data";

const sandboxProvider = () =>
  docker({
    mounts: [
      { hostPath: DATA_ROOT_HOST, sandboxPath: DATA_ROOT_SANDBOX, readonly: true },
    ],
    env: { MOONDATA_DATA_ROOT: DATA_ROOT_SANDBOX },
  });

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
