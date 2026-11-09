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
| **`SoftwareGatewayArchitect`** (Upcoming) | Design and implementation of the mobile host gateway, BLE audio multiplexer, and cross-surface display router. | `inherit` | **Planned** | `mobile-host/` codebase & LiveKit agent runtime |
| **`WearableOSDeveloper`** (Upcoming) | Lightweight wearable OS/firmware for Bench POC (Opus-over-GATT, text HUD buffer, IMU fusion). | `inherit` | **Planned** | `firmware/` codebase & simulator |

---

## 3. Subagent Operating Principles

1. **Evidence Before Assertions**: Every subagent must verify claims against real physical datasheets, schematic pinouts, and open-source code repositories.
2. **Zero Hallucination of APIs**: Verify exact SDK versions (e.g., LiveKit Agents 1.x `AgentSession` vs deprecated 0.x `MultimodalAgent`; Android 12+ `AudioManager.setCommunicationDevice`).
3. **Decoupled Architecture**: Subagent deliverables must adhere to clean modular boundaries (Firmware $\leftrightarrow$ Gateway Protocol $\leftrightarrow$ Cloud Agent Engine).
4. **Lifecycle Discipline**: Subagents are dispatched with explicit scope and retired or transitioned upon verification of deliverables.
