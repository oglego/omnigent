# Agent YAML spec

Omnigent can run an agent from a single YAML file:

```bash
omnigent run path/to/agent.yaml
```

Use this file to choose the harness/model, write the system prompt, and declare
which tools, sub-agents, OS access, and policies the agent can use.

## Minimal agent

```yaml
name: hello_agent
prompt: |
  You are a concise assistant. Answer directly and ask a follow-up question when
  the request is ambiguous.

executor:
  harness: claude-sdk
  model: databricks-claude-sonnet-4-6
  auth:
    type: databricks
    profile: oss
```

`prompt` may also be replaced by `instructions: AGENTS.md`; relative paths are
resolved from the YAML file's directory.

## Common top-level fields

| Field | Required? | Purpose |
| --- | --- | --- |
| `name` | Recommended | Stable identifier shown in sessions and logs. |
| `prompt` | Usually | Inline system prompt. |
| `instructions` | Optional | Inline instructions or a path to an instructions file. If set, it takes precedence over `prompt`. |
| `executor` | Recommended | Harness, model, and auth settings. |
| `tools` | Optional | MCP tools, Python function tools, sub-agents, handoffs, or inherited tools. |
| `policies` | Optional | Guardrails that inspect requests, responses, tool calls, or tool results. |
| `params` | Optional | Typed user parameters available to tools/skills. |
| `os_env` | Optional | Enables local OS tools such as file reads, writes, edits, and shell commands. |
| `terminals` | Optional | Named interactive terminal environments the agent can launch. |
| `async` | Optional | Whether async work tools are exposed. Defaults to `true`. |
| `cancellable` | Optional | Whether the session can be cancelled. Defaults to `true`. |
| `timers` | Optional | Whether timer tools are exposed. Defaults to `false`. |

## Executor

```yaml
executor:
  harness: claude-sdk        # claude-sdk, openai-agents, codex, cursor, kiro-native, pi, antigravity, qwen, kimi, copilot, hermes, ...
  model: databricks-claude-opus-4-7
  auth:
    type: databricks
    profile: oss             # Databricks profile for model routing
```

Set the Databricks profile under `executor.auth`. The older top-level
`executor.profile` shorthand is legacy and should not be used in new specs.

The `cursor` harness (Cursor's `cursor-agent`) is the exception: it talks
only to Cursor's own backend and has no custom API base-URL, so the Databricks
gateway / `auth.type: databricks` does not apply. Authenticate it with
`CURSOR_API_KEY` (or a prior `cursor-agent login`), optionally pinned via
`auth: {type: api_key, api_key: ${CURSOR_API_KEY}}`, and choose a Cursor model
id (e.g. `auto`, `gpt-5`) rather than a `databricks-*` id.

The `kiro-native` harness is the native Kiro CLI terminal path used by
`omnigent kiro`. It requires `kiro-cli` on `PATH` and Kiro's own login/auth; it
does not use Databricks, OpenAI, or Anthropic provider credentials. Plain
`harness: kiro` is not a generic Omnigent harness id. Kiro's TUI remains the
authoritative approval surface; supported one-time tool approvals can also be
mirrored into Chat cards, while persistent trust choices remain explicit Kiro
TUI/flag actions. See `kiro-native-elicitation.md`.

### Antigravity (Gemini)

`harness: antigravity` runs the agent through Google's
[Antigravity SDK](https://pypi.org/project/google-antigravity/)
(`pip install "omnigent[antigravity]"`). It defaults to **Gemini 3.5 Flash**
and can also drive Claude / GPT-OSS. Authenticate with an Antigravity /
Gemini API key, or Vertex AI (`project` / `location`) — the SDK is
Gemini-native and has no OpenAI-compatible gateway / Databricks path.

```yaml
executor:
  harness: antigravity         # aliases: agy, google-antigravity
  model: gemini-3.5-flash
  auth:
    type: api_key
    api_key: ${GEMINI_API_KEY}     # or ANTIGRAVITY_API_KEY
```

### GitHub Copilot

`harness: copilot` runs the agent through the
[GitHub Copilot SDK](https://pypi.org/project/github-copilot-sdk/)
(`pip install "omnigent[copilot]"`). The SDK bundles the Copilot CLI it drives
as a backing server, so no separate CLI install is needed. Like cursor and
antigravity it talks only to GitHub's Copilot backend — there is no Databricks
gateway / `auth.type: databricks` path. Authenticate with a **GitHub token** that
carries Copilot access: a fine-grained PAT with the "Copilot Requests"
permission, or an OAuth token from the GitHub CLI (`gh auth token`) / Copilot
CLI. Resolution: spec `auth.api_key` → a token registered via `omnigent setup`
(the `copilot:` config block) → ambient `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` /
`GITHUB_TOKEN`. Choose a Copilot model id (e.g. `claude-haiku-4.5`, `gpt-5-mini`,
or omit for auto-select) rather than a `databricks-*` id. Classic `ghp_` PATs are
not accepted by Copilot.

```yaml
executor:
  harness: copilot             # alias: github-copilot
  model: claude-haiku-4.5      # a Copilot model id; omit for auto-select
  auth:
    type: api_key
    api_key: ${GH_TOKEN}       # a GitHub token with Copilot access
```

To route through OpenRouter / a gateway, declare a key/gateway provider in
`~/.omnigent/config.yaml` and reference it (`auth: {type: provider, name: …}`),
or set `auth.base_url` to the OpenAI-compatible endpoint alongside the key.
For Databricks, use `auth: {type: databricks, profile: …}`.

### Kimi Code

`harness: kimi` runs the agent through Moonshot AI's
[Kimi Code CLI](https://github.com/MoonshotAI/Kimi-Code) headlessly via
`kimi --print --output-format stream-json` per turn. Install the binary
with `curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash`
and authenticate once with `kimi login` (OAuth or a Moonshot API key).

```yaml
executor:
  harness: kimi               # alias: kimi-code
  model: kimi-k2-turbo
```

By default Kimi authenticates against Moonshot AI's backend — Omnigent
declares no `executor.auth` block. To route through a gateway, either set
`HARNESS_KIMI_GATEWAY_BASE_URL` + `HARNESS_KIMI_GATEWAY_API_KEY` in the
shell, declare a key/gateway provider in `~/.omnigent/config.yaml`, or use
`executor.auth: {type: databricks, profile: …}` and let Omnigent resolve
the workspace.

CLI flags such as `--harness` and `--model` can override or supply missing
executor values for a run. Databricks credentials come from the spec's
`executor.auth` block or your `omnigent setup` provider config — there is
no profile flag.

### Qwen Code

`harness: qwen` runs the agent through [Qwen Code](https://github.com/QwenLM/qwen)
(`npm install -g @qwen-code/qwen-code`). It drives the `qwen` CLI in ACP mode
(`qwen --acp`).

```yaml
executor:
  harness: qwen                # aliases: qwen-code
  model: qwen/qwen-2.5-coder
```

CLI flags such as `--harness qwen` and `--model <id>` can override or supply
missing executor values.

### OpenAI-compatible / local servers

`harness: openai-agents` is the generic harness for anything speaking the
OpenAI wire protocol. Unlike `claude-sdk` / `codex` / `pi`, it doesn't wrap a
vendor CLI or SDK with its own execution loop — it's a bare model-calling
client, pointed at any server that implements the OpenAI API shape. This
makes it the harness to use for OpenAI itself, an OpenAI-compatible gateway,
**or a locally-hosted model** — e.g. a GGUF file served by
[`llama.cpp`](https://github.com/ggml-org/llama.cpp)'s `llama-server`,
[Ollama](https://ollama.com/), or LM Studio, all of which expose an
OpenAI-compatible endpoint.

```yaml
# llama-server (default port 8080)
executor:
  harness: openai-agents
  model: <model id/alias your server reports>
  auth:
    type: api_key
    api_key: "local"                       # see note on api_key below
    base_url: "http://localhost:8080/v1"   # llama-server default
  config:
    use_responses: false                   # required for /chat/completions-only servers
```

**`api_key`** — set to any non-empty string (e.g. `"local"` or
`"not-needed"`). The OpenAI SDK requires a value even when the server
doesn't authenticate. Some servers (e.g. vLLM with `--api-key`) do validate
the key — use the actual key in those cases.

**`model`** should match whatever identifier the server reports — query
`GET /v1/models` (`curl http://localhost:8080/v1/models`) if you're not sure
what to put here. Most single-model local servers (like `llama-server`)
accept any value and just answer with the model they have loaded. For
multi-model servers like Ollama, `model` must exactly match a model you have
pulled (e.g. `llama3.2:latest`); an unrecognised name 404s. Run `ollama list`
or query `GET /v1/models` to see available names.

**`use_responses`** controls whether the harness talks to the newer
`/responses` endpoint or the older `/chat/completions` endpoint. The default
is dynamic:

- **OpenAI models and non-Databricks endpoints** — defaults to `true`
  (`/responses`).
- **Databricks-hosted non-GPT models** (e.g. `databricks-claude-*`,
  `databricks-kimi-*`) — defaults to `false` (`/chat/completions`),
  because only GPT serving on the Databricks gateway speaks the Responses
  wire.

Most local OpenAI-compatible servers (`llama-server`, Ollama, LM Studio,
etc.) only implement `/chat/completions`. 

**Environment-variable alternative** — you can skip the `auth:` block
entirely and set the standard OpenAI SDK variables in your shell:

```bash
export OPENAI_BASE_URL="http://localhost:8080/v1"
export OPENAI_API_KEY="local"
```

The harness falls back to these when no explicit auth is declared.
`auth.base_url` (which maps to `HARNESS_OPENAI_AGENTS_GATEWAY_BASE_URL`
internally) takes priority over `OPENAI_BASE_URL` when both are set.

Unlike the CLI-wrapped harnesses, `openai-agents` has no file/shell tools of
its own — there's no underlying CLI to inherit them from. If your agent
needs to read/write files or run commands, you must declare `os_env`
explicitly (see [Local OS access](#local-os-access) below); without it, the
model has no way to touch the filesystem no matter how capable it is.

Also worth knowing when working with local models specifically: tool/function
-calling reliability varies a lot by model and quantization. If `os_env`
tools are declared and available but the model still doesn't seem to use
them, that's more often a model-capability limitation than a configuration
problem — check whether your specific GGUF build/quant is documented as
supporting tool calling before assuming the harness setup is wrong.
Streaming is enabled by default. Most local servers support it, but if you
see broken or incomplete responses, verify your server's SSE streaming
support.

## Local OS access

Declare `os_env` only for agents that need local file/shell tools.

```yaml
os_env:
  type: caller_process
  cwd: .
  sandbox:
    type: linux_bwrap
    write_paths:
      - .
    allow_network: true
```

For trusted local development, examples may use `sandbox.type: none`:

```yaml
os_env:
  type: caller_process
  cwd: .
  sandbox:
    type: none
```

Prefer the narrowest filesystem and network access that supports the task. Do
not pass secrets through the environment unless the tool genuinely needs them.

You usually don't need to choose a `sandbox.type` — omit it and Omnigent picks
the platform default (`linux_bwrap` on Linux, `darwin_seatbelt` on macOS), so the
same YAML works across platforms. For the full set of sandbox options, how to
share one policy across `sys_os_*` and terminals, and how to set up network
egress rules, see the `sandbox:` examples below and the sandbox source under `omnigent/inner/`.

## Tools

Tools are declared under `tools` by name.

### MCP server

```yaml
tools:
  github:
    type: mcp
    command: uv
    args:
      - run
      - python
      - -m
      - my_package.github_mcp
    tools:
      - search_issues
      - get_pull_request
```

MCP tools can also point at a remote URL:

```yaml
tools:
  docs:
    type: mcp
    url: https://example.com/mcp
    headers:
      Authorization: Bearer ${TOKEN}
```

### Python function tool

```yaml
tools:
  summarize_file:
    type: function
    description: Summarize a local text file.
    callable: my_package.tools.summarize_file
    parameters:
      type: object
      properties:
        path:
          type: string
      required: [path]
```

For client-provided tools, use `runtime: client` and do not set `callable`.

### Tool sandbox containers

Local Python tools can run inside a container image by declaring a sandbox image.
Use `container_image` for new specs; `docker_image` remains accepted as a
deprecated alias for backwards compatibility. Set `container_runtime: podman` to
run the image with Podman instead of Docker.

```yaml
tools:
  sandbox:
    container_image: python:3.12-slim
    container_runtime: podman  # optional; defaults to docker
```

### Sub-agent tool

```yaml
tools:
  reviewer:
    type: agent
    description: Review proposed code changes.
    prompt: |
      You are a careful code reviewer. Focus on correctness, tests, security,
      and maintainability.
    executor:
      harness: claude-sdk
      model: databricks-claude-sonnet-4-6
    os_env: inherit
    pass_history: true
    max_sessions: 2
```

Each sub-agent picks its own `executor.harness` and `model`, so an orchestrator
can mix harnesses by role — e.g. a `cursor` coder with a `claude-sdk`
reviewer:

```yaml
tools:
  coder:
    type: agent
    executor:
      harness: cursor      # Cursor model id (e.g. gpt-5, auto), not a databricks-* id
      model: gpt-5
```

Use `tools.<name>: inherit` to inherit a tool from a parent agent, or
`tools.<name>: self` / `spec: self` for a sub-agent that clones the parent spec.

## Policies

Policies can inspect requests, responses, tool calls, and tool results.

```yaml
policies:
  pii_guard:
    type: function
    handler: my_package.policies.pii_guard
    on: [request, response]
```

A factory can be configured with `factory_params`:

```yaml
policies:
  workspace_policy:
    type: function
    handler: my_package.policies.make_workspace_policy
    factory_params:
      allowed_hosts:
        - example.cloud.databricks.com
```

## Terminals

Terminals are named interactive shell environments that the agent can launch.

```yaml
terminals:
  bash:
    command: bash
    args: [-l]
    os_env: inherit
    allow_cwd_override: true
    allow_sandbox_override: false
    scrollback: 10000
```

Use `os_env: inherit` to give the terminal the same sandbox as the agent, or
alias a shared `sandbox:` block so `sys_os_*` and the terminal enforce the same
policy. Keep `allow_sandbox_override: false` unless you intend to let the
launcher weaken the sandbox at launch time.

## Complete example

```yaml
name: coding_agent
prompt: |
  You are a coding agent. Inspect files before editing, run targeted tests, and
  summarize changes with validation results.

executor:
  harness: claude-sdk
  model: databricks-claude-sonnet-4-6
  auth:
    type: databricks
    profile: oss

async: true
cancellable: true

os_env:
  type: caller_process
  cwd: .
  sandbox:
    type: linux_bwrap
    write_paths: [.]
    allow_network: true

terminals:
  zsh:
    command: zsh
    args: [-l]
    os_env: inherit
    allow_cwd_override: true

tools:
  repo_search:
    type: function
    description: Search repository files for a pattern.
    callable: my_package.tools.repo_search
    parameters:
      type: object
      properties:
        query:
          type: string
      required: [query]
```

## Validation tips

- Keep examples free of secrets, workspace URLs, customer data, and private
  Databricks-only configuration unless the example is explicitly internal.
- Prefer `instructions: AGENTS.md` for long prompts that are shared with other
  tooling.
- Start from a bundled example such as `examples/polly/config.yaml` or
  `examples/debby/config.yaml` and remove tools you do not need.
- Run the YAML before publishing it:

  ```bash
  omnigent run path/to/agent.yaml -p "Say hello"
  ```
