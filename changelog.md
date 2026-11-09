# Changelog: Project PA

All notable decisions, milestones, architectural transitions, and code changes are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] - 2026-11-09

### Added
- **Initial Repository Setup**: Initialized Git version control in `c:/Projects/PA`.
- **Project Governance & Memory**:
  - `memory.md`: Core system thesis, architecture decision records (ADR-001 through ADR-004), hardware topology roadmap, and open-source foundation references.
  - `agents.md`: Subagent registry defining roles, capabilities, and coordination protocols for orchestrator, software gateway, wearable OS, and research workers.
  - `changelog.md`: Continuous project journal.
- **Deep Technical Investigation Report**: Synthesized comprehensive 4-domain investigation covering:
  - JBD 0.13" MicroLED + Mitsui MR-7 diffractive waveguide optical modeling (>1,000 nits eye luminance).
  - USound Ganymede MEMS speaker + Tarvos 1.2 30Vpp Class-H boost amplifier with 20–24 dB dipole phase cancellation.
  - ST LIS25BA bone-conduction VPU for whisper-quiet and noise-immune voice input.
  - Maxim MAX77654 SIMO PMIC power tree respecting IEC 62368-1 43°C skin-contact safety ceiling.
  - End-to-end LiveKit Agents 1.x multimodal architecture achieving sub-320ms latency.
  - Scaled Bill of Materials ($149.20 at 10,000 units).

### Changed
- **Architectural Pivot (ADR-001)**: Per user directive, prioritized the **Software / Gateway / OS stack first** before hardware fabrication. Established hardware trajectory: **Developer Bench POC** first, followed by **Tier 3 Standalone Pocket Puck + Eyewear**.
- **Development Environment Selected (ADR-005)**: Selected **Dual-Platform Dev Gateway & Wearable Simulator**: Python LiveKit Agents 1.x backend + Web-based Wearable Simulator (HUD eyebox, simulated bone-conduction VPU, dipole speaker) + WebRTC Ambient Screen Receiver.
