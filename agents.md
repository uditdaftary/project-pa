# Subagents Registry & Coordination Protocol: Project PA

This document tracks all active, completed, and planned subagents, their operational roles, interfaces, and orchestration protocols for Project PA.

---

## 1. Orchestration Model

The parent agent operates as the **Sole Orchestrator**, serving as the single point of contact with the user. Specialized subagents are spawned for deep research, firmware development, gateway middleware, and agent runtime engineering, reporting back to the parent orchestrator upon task completion.

```
                  +------------------------------------+
                  |         PARENT ORCHESTRATOR        |
                  |     (Sole User Contact Point)      |
                  +-----------------+------------------+
                                    |
          +-------------------------+-------------------------+
          |                         |                         |
          v                         v                         v
+--------------------+    +--------------------+    +--------------------+
|  DeepInvestigator  |    |  Gateway / OS Dev  |    |  Hardware Bench    |
|  (Research & Aud)  |    |  (Software Stack)  |    |  (POC & Schematics)|
+--------------------+    +--------------------+    +--------------------+
```

---

## 2. Active & Completed Subagents

| Subagent Name | Role / Task | Workspace | Status | Output Artifact |
| :--- | :--- | :--- | :--- | :--- |
| **`DeepInvestigator`** (`eba88b35`) | Deep research into optics, audio, silicon, and open-source stacks. | `inherit` | **Completed** | Master Investigation Blueprint (4-subagent synthesis) |
| ↳ `DeepInvestigatorWorkerL0` (`2800235d`) | Initial exploration of hardware landscape, protocols, and BOM. | `inherit` | **Completed** | Initial Technical Report |
| ↳ `DeepInvestigatorImprovementWorker` (`98ea7f75`) | Technical audit, error correction (Tarvos piezo amp, LiveKit 1.x, Omi Opus-GATT). | `inherit` | **Completed** | Audited Evidence Dossier |
| **`DeepCoder`** (`1802412f`) | Implement core TLV protocol, gateway server, hybrid agent engine, wearable simulator, and ambient screen receiver across 4 parallel streams. | `inherit` | **Completed** | `core/`, `agent_engine/`, `gateway/`, `simulator/`, `ambient_screen/`, `tests/` (43 passing tests) |
| **`ScrutinyTeam`** (`8d2edda5`) | Adversarial code review across correctness, security, architecture, and bug taxonomies. | `inherit` | **Completed** | Itemized audit dossier (`bugs.md` with 27 bugs) |
| **`TeamAlpha`** (`b567f431`) | Competitive resolution: Architectural lead & peer debate. | `inherit` | **Completed** | Unified Proposal Alpha |
| **`TeamBeta`** (`4a3cf0e7`) | Competitive resolution: Low-level systems lead & peer debate. | `inherit` | **Completed** | Unified Proposal Beta |
| **`FixTeam`** (`71c2adef` / `e13df045`) | Implement 27 bug fixes across 4 streams, harden against adversarial edge cases, sync GitHub issues and PRs. | `inherit` | **Completed** | 72 passing tests, 27 closed GitHub issues, 4 merged PRs |

---

## 3. Post-Sprint Quality & Competitive Resolution Registry (ADR-009)

When the development sprint finishes, the following multi-agent review pipeline executes:

1. **Review Scrutiny Team (4 Agents)**:
   - `Reviewer-Correctness`: Correctness, edge cases, protocol framing integrity.
   - `Reviewer-Security-Thermals`: Concurrency, input sanitization, thermal/power invariants.
   - `Reviewer-Architecture`: 5-axis code quality, dependency discipline, module coupling.
   - `Reviewer-BugHunter`: Adversarial bug hunting across all 14 bug taxonomies -> `bugs.md`.
2. **Competitive Resolution Teams (2 Teams of 2 Agents)**:
   - **Team Alpha** (`AlphaLead`, `AlphaArchitect`): Debates issues and formulates Unified Approach Alpha.
   - **Team Beta** (`BetaLead`, `BetaArchitect`): Debates issues and formulates Unified Approach Beta.
3. **Orchestrator Selection**: Evaluates Alpha vs. Beta proposals and synthesizes the Master Fix Plan.
4. **Fix Execution Team (4 Agents)**:
   - `FixAgent-Protocol`, `FixAgent-Audio`, `FixAgent-Gateway`, `FixAgent-UI`: Deploy fixes and verify tests.
5. **GitHub Integration**: Posts issues and PR review comments via GitHub CLI (`gh`).

---

## 3. Subagent Operating Principles

1. **Evidence Before Assertions**: Every subagent must verify claims against real physical datasheets, schematic pinouts, and open-source code repositories.
2. **Zero Hallucination of APIs**: Verify exact SDK versions (e.g., LiveKit Agents 1.x `AgentSession` vs deprecated 0.x `MultimodalAgent`; Android 12+ `AudioManager.setCommunicationDevice`).
3. **Decoupled Architecture**: Subagent deliverables must adhere to clean modular boundaries (Firmware $\leftrightarrow$ Gateway Protocol $\leftrightarrow$ Cloud Agent Engine).
4. **Lifecycle Discipline**: Subagents are dispatched with explicit scope and retired or transitioned upon verification of deliverables.
