# NVIDIA (NVDA) — Earnings, Roadmap & Supply Chain Facts
*As of November 21, 2026*

---

## 1. Recent Earnings & Financial Guidance

### Q3 FY2027 Results (Quarter Ended October 25, 2026; Reported November 17, 2026)
*Sources: NVIDIA Q3 FY27 Press Release, SEC Form 10-Q, Seeking Alpha Earnings Transcript*
- **Total Revenue:** **$115.8B** (+103% YoY, +20% QoQ vs. Q2 FY27's $96.2B), beating Wall Street consensus (~$109.3B).
- **Data Center Revenue:** **$107.6B** (+110% YoY; ~93% of total revenue):
  - *Hyperscale:* **$60.1B** (+71% YoY)
  - *AI Clouds, Industrial & Enterprise:* **$47.5B** (+195% YoY)
- **Other Reporting Segments:** Compute & Networking **$106.0B**; Graphics **$9.8B**; Edge Computing **$8.2B**.
- **Profitability & Margins:**
  - GAAP Net Income: **$65.3B** (vs. $31.9B in Q3 FY26)
  - Diluted EPS: GAAP **$2.70** | Non-GAAP **$2.68** (vs. ~$2.47–$2.48 consensus)
  - Gross Margin: GAAP **74.8%** | Non-GAAP **74.9%**
- **Capital Allocation:** Returned **$28.1B** in Q3 via buybacks and dividends. Following an additional **$150B** authorization in September 2026, total remaining non-expiration buyback capacity exceeds **$220B**. Declared **$0.25/share** quarterly dividend payable December 23, 2026.

### Q4 FY2027 & FY2028 Outlook (Issued November 17, 2026)
- **Q4 FY27 Revenue:** **$130.0B ± 3%** (ahead of ~$125.3B consensus; reflects an extra week in fiscal Q4).
- **Q4 FY27 Gross Margin:** **71.0%–72.0% ± 50 bps** (GAAP and Non-GAAP), stepping down sequentially during early next-gen system ramps.
- **Q4 FY27 Operating Expenses:** **~$10.7B** Non-GAAP | **~$11.0B** GAAP.
- **China Assumption:** Forward guidance assumes **zero** Data Center compute revenue from China.
- **FY28 Growth Outlook:** Raised to **~75% YoY** revenue growth (up from prior 70% outlook) off the higher FY27 base.

---

## 2. Product Roadmap: Blackwell to Vera Rubin & Rubin HPC

- **Blackwell & Blackwell Ultra (B200 / B300, GB200 NVL72):** Primary workhorse of 2025–2026 deployments; built on custom **TSMC 4NP** process nodes using **CoWoS-L** packaging.
- **Vera Rubin Platform (R100 GPU + Vera CPU / NVL72):** Achieved the fastest product ramp in NVIDIA history in Q3 FY27, generating nearly **$20B** in QoQ revenue growth. Transitions to **TSMC 3nm (N3P/N3X)** with **8-stack HBM4** (custom logic base dies). Initial shipments deployed at **Microsoft (MSFT) Azure**, **Alphabet (GOOGL) Google Cloud**, **Oracle (ORCL) OCI**, **CoreWeave**, and **Nebius**.
- **SC26 Roadmap Expansions (Chicago, November 2026):**
  - **Rubin HPC (slated 2028):** Science-focused variant featuring **>50,000 CUDA cores** (>2x baseline Rubin general-purpose cores), full **FP64-to-FP4** precision, dedicated sparse-data acceleration, and **7th-gen NVLink**.
  - **Vera CPU MGX Racks (early 2027):** Liquid-cooled HPC racks (192 Vera CPUs/rack, Quantum-X800 InfiniBand, >200 TB/s aggregate memory bandwidth) shipping via **Dell, HPE, Lenovo, and Supermicro**.
- **Rubin Ultra (2027–2028 target):** Roadmap extension toward **TSMC N2 (2nm)**; initial 4-die architecture faces physical packaging redesign pressure (see below).

---

## 3. Investment Themes, Capacity & Supply Chain Relationships

### Advanced Semiconductor Packaging
- **TSMC (`TSM`):** Remains the definitive volume gatekeeper via **CoWoS-L** advanced packaging and leading-edge wafer nodes (N4P → N3P/N3X → N2). NVIDIA has historically secured **~60% of TSMC's total CoWoS capacity**, squeezing rivals such as **AMD** and custom ASIC designers. Multi-die **Rubin Ultra** (4-die blueprint) has encountered **substrate warpage** and thermal stress limits in CoWoS-L, forcing structural/yield re-evaluations.
- **Apple (`AAPL`):** As TSMC's largest customer for leading-edge logic wafers (3nm and next-gen nodes for A-series/M-series silicon), AAPL's massive volume commitments directly shape TSMC's fab capex and foundry/packaging capacity allocation alongside NVDA.
- **Memory & OSAT Partners (`SK Hynix`, `Amkor`, `SPIL`):** **SK Hynix** leads HBM4 supply and partners directly with TSMC to fabricate HBM4's custom logic base dies. To reduce Taiwan single-point-of-failure risk, NVDA is qualifying U.S. reshoring via **TSMC Fab 21 (Phoenix, AZ)** for wafers and **Amkor (Peoria, AZ)** plus **SPIL** for back-end packaging/testing.

### AI Infrastructure & Capex
- **Hyperscaler Spending (`MSFT`, `AMZN`, `GOOGL`):** Global hyperscaler capex remains near record levels (~$220B AMZN, $195B–$205B GOOGL, ~$170B MSFT). **MSFT** adjusted portions of its FY26/FY27 capex pacing due to timing shifts and third-party GPU contract delivery extensions, pushing some realizations into later fiscal halves.

### AI Data Center Power & Cooling
- **Vertiv (`VRT`):** Launched its **ATLAS Lab**, integrating directly with the **NVIDIA DSX AI Factory Platform** (via Omniverse digital twins) to pre-validate megawatt-scale thermal and power loads ahead of Rubin-class silicon deployment.
- **High-Voltage Power Transition:** Per Dell'Oro Group, rack-scale AI density is forcing data centers off traditional 50V busbars toward **400/800 Vdc** power architectures to support NVL72 and Rubin clusters.
