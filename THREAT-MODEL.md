# OSIRIS Geo Hub Phase 6B Threat Model

## Scope and conclusion

Assessment date: 2026-09-14. Phase 6B.1 was read-only. Phase 6B.2 then changed staging authorization, the curator capability manifest, and the staging MCP credential; it did not touch production. Secret values were not collected or included in this report.

**Conclusion: `geo-curator` is unsafe as a publication boundary today.** Its MCP correctly omits publication operations, but the profile has local `terminal`, `code_execution`, file, browser, and `computer_use` toolsets. The local terminal can use the available Docker daemon. Docker can inspect container environments and execute commands in the MCP, API, and PostGIS containers. The shared Geo Hub `ADMIN_API_TOKEN` then authorizes staging, commit, deletion, source sync, and all other admin API routes. Removing only `terminal` is insufficient because `code_execution` exposes a terminal function and `computer_use`/browser can recreate direct host or Admin UI access.

The Phase 6A MCP boundary is a useful product-policy guard, not an authorization boundary. Do not add an agent-facing commit tool until the profile and backend authorization changes below have been reviewed and applied.

## Phase 6B.2 implementation and verification

Phase 6B.2 applies the recommended preparation boundary to staging. `geo-curator`
now exposes only `web`, `clarify`, and the explicitly allowlisted `geo-osiris`
MCP. It disables terminal, code execution, computer use, file, and browser
toolsets; its browser configuration also denies private URLs and real-profile
use. DeepWiki and n8n are disabled. The remaining `web` capability is for
public research; URL safety rejected localhost, loopback, RFC1918, `.local`,
Docker service names, and Portainer-style private names during verification.

The Geo API now enforces static bearer scopes. `GEO_READ_TOKEN` grants
`geo.read`; `GEO_STAGE_TOKEN` grants `geo.read` and `geo.stage`;
`GEO_PUBLISH_TOKEN` grants `geo.read` and `geo.publish`; and `GEO_ADMIN_TOKEN`
Bearer challenge; a valid credential lacking the required scope returns 403.
`ADMIN_API_TOKEN` is temporarily accepted as full admin only for migration and
must be removed after scoped credentials are deployed everywhere.

| Scope | Routes |
|---|---|
| `geo.read` | All admin GET routes for layers, features, imports, import rows, and sources |
| `geo.stage` | Create/update layers and features; stage imports; resolve import rows |
| `geo.publish` | Commit an import only |
| `geo.admin` | Archive features, cancel imports, and source sync; includes all other scopes |

The staging MCP requires only `GEO_STAGE_TOKEN`; it no longer accepts or
receives `ADMIN_API_TOKEN`. A live request from the MCP container using that
credential to the import commit endpoint returned 403. The live MCP exposes 21
read/staging tools, with no commit, cancellation, archive, delete, or source
sync tool. It staged a duplicate CSV row, reported one unresolved candidate,
resolved that row as `skip`, and then reported the staging import commit-ready.
It could not commit it.

The current staging rollout injects a freshly generated stage token into the
running API and MCP only. Store it in the normal staging secret mechanism
before an ordinary redeploy; do not place the publish or admin credentials in
the MCP compose environment. Production remains unchanged. Before production,
provision distinct scoped secrets, deploy the API and MCP together, rotate and
remove the legacy admin token, verify the same 403 rejection, and keep the
production Docker and database networks unreachable from Hermes hosts.

## 1. Current architecture

```text
Hermes base/default or geo-curator profile
  ├─ local terminal, code execution, file, browser, computer use
  └─ Geo MCP stdio helper
       docker exec -i -e GEO_HUB_MCP_MODE={read|staging}
         geo-osiris-mcp
           └─ shared staging Docker network
                ├─ geo-api:8000 (not host-published)
                ├─ postgis:5432 (not host-published)
                ├─ geo-admin:3000 (host-published as 8081)
                └─ OSIRIS UI (host-published as 3001)
```

Observed running containers are `geo-osiris-mcp`, `osiris-staging-geo-api-1`, `osiris-staging-geo-admin-1`, and `osiris-staging-postgis-1`. All are attached to `osiris-staging_osiris-staging`. The native host cannot reach Geo API at `127.0.0.1:8000`; Geo Admin is reachable at `127.0.0.1:8081`. Network isolation therefore protects Geo API only from a non-Docker host client, not from an agent with Docker access.

The MCP is run with `docker exec`; its process environment contains `GEO_API_URL` and `ADMIN_API_TOKEN`. The API environment contains the same admin token, an AEMET credential, and `DATABASE_URL`; PostGIS contains `POSTGRES_PASSWORD`. The MCP runs as user `mcp`; the API as `appuser`; PostGIS has its image default user. None is privileged and none has the Docker socket mounted. These controls do not constrain the native Hermes process, which can invoke Docker directly.

## 2. Protected assets

- Published Geo Hub features, layer configuration, imports, external sources, provenance, and approval records.
- PostGIS data and persistent volumes.
- `ADMIN_API_TOKEN`, database credentials, AEMET credential, Admin UI credential, deployment secrets, container environments, backups, and compose/environment files.
- Docker control plane and its ability to inspect, exec, replace, stop, or reconfigure containers.
- OSIRIS and Geo Hub availability.
- Approval decisions and the import/version they authorize.

## 3. Trust zones and boundaries

| Zone | Current authority | Boundary assessment |
|---|---|---|
| Human operator | Desktop, Docker, Geo Admin, emergency DB administration | Trusted administrator; must remain distinct from agent authority. |
| Hermes base/default | General local tools plus read-mode Geo MCP | No effective Geo authorization boundary: local Docker can start a staging MCP or inspect the existing MCP. |
| Hermes geo-curator | Staging MCP plus general local tools | No effective publication boundary; local tools bypass MCP policy. |
| Geo MCP read/staging processes | HTTP client on shared Docker network | Tool registration distinguishes modes, but both processes carry the same all-admin token. |
| Geo Hub API | Admin HTTP endpoints | Single bearer token authenticates every admin operation, including commit. |
| Geo Admin UI | Host port 8081, admin token and UI password in its environment | Authenticated UI is an administrative path and can be reached by host browser/computer-use capabilities. |
| Docker host | Docker Desktop daemon and socket | Native Hermes terminal currently has daemon access; this crosses every container boundary. |
| PostGIS | Private Docker network, password environment | Docker access crosses the network and credential boundary. |
| Future approval authority | Not implemented | Must be separate from agent profiles and hold the only publish credential. |

## 4. Capability inventory

### Hermes profiles and tools

- The base configuration is the effective default profile; no separate `default` profile directory exists.
- `geo-curator` has an independent profile directory and its own config, but it inherits/enables: `browser`, `code_execution`, `computer_use`, `file`, `terminal`, and `web` in its CLI toolsets.
- Both base/default and curator register `geo-osiris` through `docker exec`. Base/default injects `GEO_HUB_MCP_MODE=read`; curator injects `staging`.
- The curator's cached MCP schema has 21 Geo tools: 14 common/read tools and seven staging tools. It has no commit, cancel, publish, archive, delete, or source-sync MCP tool.
- The only other enabled MCP visible in the curator cache is DeepWiki, which exposes documentation-oriented tools. `n8n-mcp` is configured but disabled. No enabled shell, filesystem, SSH, Docker, or generic HTTP MCP was found.
- Hermes profile state and MCP configuration are profile-scoped through `HERMES_HOME`; this prevents accidental configuration/state mixing. It is not an OS security sandbox. Gateway code can resolve a supplied profile scope, and profile separation does not prevent a profile with local execution from reaching shared host resources.

### Execution and browser controls

- `terminal.backend` is `local`; Docker CLI is installed, the Docker Desktop context is active, and the daemon is usable by the invoking user.
- `code_execution` can call Hermes `terminal()` as well as read/write/patch files. It is shell-equivalent for this threat model.
- Browser configuration has `allow_private_urls: true` and `use_real_profile: true`. It is therefore unsafe to assume browser research is public-web-only. It can reach host-private services such as Geo Admin.
- `computer_use` is registered. CuaDriver is installed and healthy, but its macOS TCC status is currently unknown because its daemon is not running. If Accessibility and Screen Recording are granted, it can operate desktop applications and their authenticated sessions; treat it as host control, not a constrained web browser.
- File tools can read files available to the Hermes process. They are conditionally unsafe because local secret files, profile `.env` files, compose files, shell history, and Docker client configuration may be readable.

### Geo Hub authorization

- Every `/api/v1/admin/...` endpoint uses `require_admin`.
- `require_admin` compares one bearer token, `ADMIN_API_TOKEN`; it has no operation, role, audience, or expiry scope.
- The same token is provisioned to Geo API, Geo Admin, and Geo MCP. It therefore authorizes stage, resolve, create/update features/layers, commit, cancel, archive, and source sync if an agent obtains it.
- The MCP's read/staging gates are correctly fail-closed at registration and invocation, but are local policy gates. A stolen MCP token can call `/api/v1/admin/imports/{id}/commit` directly.

## 5. Threat scenarios and risk classification

| ID | Threat and preconditions | Current feasibility | Impact | Existing controls | Recommendation and residual risk |
|---|---|---|---|---|---|
| T1 | MCP bypass through terminal, curl, Python, or code execution. Requires a local-execution tool. | **Confirmed.** Curator has local terminal and code execution; host Docker is usable. Geo API is not host-published, but Docker reaches its network. | Critical: direct admin API, arbitrary container commands, and publication bypass. | Geo API private port; MCP omits commit. | Remove terminal and code execution from curator. Keep Geo API non-published. Residual: privileged human/developer profile remains intentionally powerful. |
| T2 | Docker bypass via `docker exec`, inspect, compose, or container replacement. Requires Docker-capable shell. | **Confirmed.** Docker CLI and active daemon are available. Containers and env-key names are inspectable. | Critical: recover credentials, execute in any service, mutate or replace stack. | Containers are unprivileged; no Docker socket inside them. | Curator/default must not have local Docker access. Docker authorization must be at OS/session level, not a prompt rule. Residual: human administrator retains Docker. |
| T3 | Direct PostGIS access via Docker exec plus DB credential. | **Confirmed capability path.** PostGIS is private but Docker reaches it; its password is in container environment. No write was attempted. | Critical: bypasses validation, provenance, duplicate detection, approval, and audit trail. | No host port is published. | Block Docker and shell from curator; place production DB on a network unavailable to agent hosts. Residual: emergency DB access is human-admin-only. |
| T4 | Token/secret exfiltration through inspect, container env, `/proc`, compose/env files, logs, or shell history. | **Confirmed for Docker inspect path.** Secret-bearing environment variable names are present in MCP, API, Admin UI, and PostGIS containers; values were deliberately not read. | Critical: shared admin token gives all API admin actions; DB password gives direct DB access. | MCP error redaction; Hermes output redaction comments. | Do not rely on output redaction. Remove access path; move publish credential to separate service; use scoped tokens. Rotate exposed credentials as part of the permission-change work. Residual: humans with Docker can access environments by design. |
| T5 | Future approval bypass by calling commit directly after approval feature is added. | **Confirmed design gap.** Current shared token already authorizes commit. | Critical: human approval becomes cosmetic. | MCP has no commit tool. | Enforce backend publish authorization with a distinct credential and approval verification. Agent must never receive that credential. |
| T6 | Cross-profile escalation or direct use of another profile's authority. | **Partially confirmed.** Hermes has profile-scoped state/config, but no OS sandbox; an agent does not need a profile switch because both current profiles expose local Docker. Gateway internals accept profile-scoped operations; no test established an autonomous UI profile switch. | High: profile labels do not contain host authority. | Separate `HERMES_HOME`, profile `.env` scopes. | Treat profiles as capability manifests, not security principals, until execution is isolated. Remove overlapping host powers. |
| T7 | Other MCP indirectly provides shell/filesystem/HTTP/Docker/n8n/SSH. | **Not found among enabled curator MCPs.** DeepWiki is the only other enabled MCP. n8n is disabled. | Medium if enabled later. | Disabled n8n MCP; current cache inventory. | Allowlist curator MCPs and review each new MCP for host/network reachability. Residual: inventory can change. |
| T8 | Computer-use or browser opens Terminal, Docker Desktop, Portainer, Geo Admin, or an authenticated browser session. | Browser private URL access and real profile are **confirmed**. CuaDriver is installed; actual desktop TCC readiness is **unknown**, so full desktop control was not demonstrated. | High today, Critical if TCC permissions/session access are active. | Geo Admin password; CuaDriver daemon currently absent. | Remove computer use from curator. Keep only a network-restricted public-web research tool. Remove/deny private URL access for curator browser. |

Risk levels reflect actual inspected paths. T6 and the full native-desktop portion of T8 retain their stated uncertainty rather than assuming capabilities that were not exercised.

## 6. Actual bypass paths

1. Curator `terminal` or `code_execution` -> Docker CLI -> inspect `geo-osiris-mcp` -> obtain shared admin token -> direct Geo API request from inside the shared network or from an exec session -> commit/publish-capable admin route.
2. Curator `terminal` -> Docker exec PostGIS -> environment credential -> `psql` -> direct mutation. This bypasses all Geo Hub application controls.
3. Curator terminal -> Docker exec Geo API or MCP -> run internal clients/code in a network namespace that reaches `geo-api:8000`.
4. Curator browser -> `127.0.0.1:8081` Geo Admin. If an Admin UI session exists or credentials are reachable through another host capability, the agent can act as an administrator.
5. Base/default profile -> local Docker -> manually invoke the staging-mode MCP command or any of paths 1-3. Read profile mode does not prevent this.

## 7. Capability matrix: current and target

| Capability | Base/default now | geo-curator now | Recommended curator | Future approval service | Human administrator |
|---|---|---|---|---|---|
| Read Geo Hub | Yes, MCP read | Yes | Yes | Minimal verification only | Yes |
| Stage imports | Bypassable through Docker despite read MCP | Yes | Yes | No | Yes |
| Resolve candidates | Bypassable through Docker despite read MCP | Yes | Yes | No | Yes |
| Request publication | No dedicated tool | No dedicated tool | Future yes, creates immutable request only | Receives request | Yes |
| Approve publication | No | No | No | No | Yes, separate authenticated channel |
| Execute publication | Bypassable today | Bypassable today | No | Yes, after verified approval | Emergency/manual only |
| Terminal / code execution | Yes | Yes | No | No | Yes, outside agent profiles |
| Docker | Yes through terminal | Yes through terminal | No | No | Yes |
| Direct Geo admin API | Bypassable | Bypassable | No | Scoped publish endpoint only | Yes |
| PostGIS | Bypassable | Bypassable | No | No | Emergency human admin only |
| Browser research | Yes, private URLs allowed | Yes, private URLs allowed | Public web only, if enforceable | No | Yes |
| Computer use | Registered | Registered | No | No | Human only |

## 8. Evaluated architectures

### Model A: restricted `geo-curator`

Remove `terminal`, `code_execution`, `computer_use`, generic file write/read beyond a dedicated intake area, Docker, and generic private-network HTTP/browser access. Retain the staging Geo MCP and bounded public-web/domain research.

Advantages: smallest change; makes MCP restrictions meaningful for preparation. Disadvantages: staging still uses an all-admin token today, so a compromise of the MCP container/token remains able to commit until API scopes exist.

### Model B: preparation and operator profiles

- `geo-researcher`: public research and read-only Geo MCP; no host execution.
- `geo-curator`: staging MCP and bounded research; no shell/Docker/code execution/computer use/private HTTP.
- `developer`: terminal/code/Docker as needed, but no Geo staging/publish credentials and never used for curation.
- `geo-operator`: do not make this an autonomous LLM profile. Use it only as a minimal service identity or human-operated interface.

Advantages: clear role separation and reduced accidental capability overlap. Disadvantages: Hermes profile isolation alone is insufficient if any role can access shared host resources.

### Model C: external approval service

Curator prepares an import and requests publication. A human approves in a separate authenticated channel. A narrowly scoped service validates the immutable request and commits. No LLM profile has a commit credential or general execution tools.

Advantages: preserves human approval even if curator instructions are compromised; strongest auditability and TOCTOU control. Disadvantages: requires backend authorization and an approval workflow.

## 9. Recommended target architecture

Adopt **Model B plus Model C**.

1. Make `geo-curator` a restricted preparation profile: staging MCP and a public-web-only research capability; no terminal, code execution, computer use, Docker, generic filesystem, generic HTTP, or browser access to private/local addresses.
2. Separate the user/host session that runs curator from any Docker-capable administrator/developer session. A profile setting alone cannot remove inherited Unix socket/CLI authority.
3. Retain a human-only developer/operations environment for Docker, Portainer, Geo Admin, backups, and emergency PostGIS work. It must not be selectable by autonomous curator jobs.
4. Before Phase 6C, replace the shared all-admin token model with backend-enforced scopes or separate service credentials. At minimum: `geo.read`, `geo.stage`, and `geo.publish`; reserve `geo.admin` for human operations. The staging credential must be rejected by commit, archive, delete, and source-sync endpoints.
5. Build an approval service, not a publisher LLM profile. Its service identity holds only `geo.publish`; it accepts a human-approved immutable request and calls the one publish endpoint.

## 10. Secrets and authorization implications

Scoped Geo Hub authorization is **required before Phase 6C**, not merely recommended. One `ADMIN_API_TOKEN` means any staging MCP token is a commit token. Removing direct host tools lowers the likelihood of theft but does not turn a shared token into a backend boundary.

Future credentials:

- Curator/MCP: `geo.read` and `geo.stage`; no publish/admin permission.
- Approval executor: `geo.publish` only; no layer administration, source sync, or database credential.
- Human administration: `geo.admin`, separately protected and never mounted into agent-facing containers.
- Database credential: never in an agent-visible container or profile. Prefer separate DB roles for API migration/runtime and backup/emergency operation.

The currently shared admin credential should be rotated when role separation is introduced because Docker inspection establishes an exposure path. Do not place the new publish credential in the curator container, profile `.env`, compose visible to curator, browser session, or a general-purpose agent process.

## 11. Approval integrity and TOCTOU requirements

An approval must authorize an immutable import version, not only an `import_id`. Persist and verify at commit time:

- approval request ID and import ID;
- layer ID and expected import state;
- valid, invalid, candidate, and resolved-candidate counts;
- canonical dataset/content hash and mapping hash/version;
- import revision or immutable version;
- requester, approver, approval timestamp, expiry, and decision reason;
- executor identity and commit timestamp.

On request, freeze the import or create an immutable snapshot. Any row resolution, mapping, dataset, layer-target, or relevant state change invalidates the approval and requires a new request. The executor must compare the stored binding against current state atomically with commit; otherwise an old approval can commit altered data.

## 12. Human approval channel assessment

| Channel | Security and auditability | Recommendation |
|---|---|---|
| Geo Admin UI | Good candidate if it has a human-only session/role, audit logging, and the curator cannot use browser/computer use to reach it. Current shared token/session model is insufficient. | Preferred after role separation. |
| Separate minimal approval UI | Best least privilege: approve/reject one immutable request; no general admin features. | Strongest long-term option. |
| Telegram interactive approval | Convenient but identity/session binding, replay protection, audit, and device compromise need careful work. | Avoid as first implementation. |
| CLI/manual action | Simple and auditable if human-only credential is used, but weaker UX and prone to operator error. | Acceptable emergency escape hatch, not primary workflow. |

Computer use must not be available to the curator if Geo Admin is an approval channel; otherwise an agent can potentially use the human browser session to self-approve.

## 13. Recommended Phase 6C design

```text
geo-curator (geo.stage token)
  -> stage, validate, resolve
  -> create immutable publication request

human approval UI (human-only authenticated role)
  -> approve request/version/hash

approval executor (geo.publish token only)
  -> atomically verify approved immutable binding
  -> commit
  -> record executor/audit event
```

The executor is a narrow service, not an LLM agent and not an MCP tool exposed to curator. It needs no shell, Docker, PostGIS access, research tools, or generic HTTP egress.

## 14. Proposed migration sequence

1. **6B.1, after review:** create restricted profile manifests and run curator in an environment without Docker/socket access. Remove terminal, code execution, computer use, private/local browser access, and generic filesystem/HTTP from curator.
2. **6B.2:** verify curator can still use public research plus the 21 intended Geo MCP tools to stage and resolve imports; verify it cannot reach Docker, localhost/private addresses, Geo Admin, or PostGIS.
3. **6B.3:** add backend-enforced scoped credentials and endpoint authorization; split and rotate the current shared admin credential. Confirm a staging token receives authorization denial on commit/admin-destructive routes.
4. **6C:** implement immutable publication requests, human approval UI/role, atomic approval verification, and narrow approval executor.
5. **6C verification:** test that an approved import changed after approval cannot commit; test curator cannot call or obtain the executor credential.
6. **6D:** deploy the same separation to production. Put production Geo API/PostGIS on a private network reachable only by scoped MCP/executor services, not the Hermes host. When Hermes and production are separate machines, firewall and service identity boundaries make this materially stronger; do not expose Docker or database ports to the Hermes machine.

## 15. Operational escape hatch

Human administrators retain a separately authenticated operations path for Docker, Portainer, Geo Admin, backups, and emergency PostGIS access. This path must use a human login/session or dedicated admin workstation, not a curator profile or a credential mounted into an agent process. Emergency direct database changes require an operator record describing the change and any resulting provenance/audit reconciliation.

## 16. Open questions

1. Can Hermes enforce a profile-specific allowlist that removes toolsets rather than copying the global list, and can it enforce a browser egress allowlist for public hosts only?
2. What OS/session mechanism will ensure the curator process cannot reach Docker Desktop even if a future tool regression exposes shell execution?
3. Is Geo Admin already capable of separate human roles/audit logs, or should Phase 6C use a minimal approval UI?
4. Does production currently publish Geo API or PostGIS ports, and where will the approval executor run relative to production networking?
5. Which agent data intake filesystem, if any, is necessary for future datasets, and can it be mounted read-only with path allowlisting?
6. What retention and review requirements apply to approval records, provenance, backups, and AEMET/amateur-radio source data?
