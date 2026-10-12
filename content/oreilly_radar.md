<!-- Page 2 of oreilly_events_06-Oct-26.md (compiled from Gmail on 6 Oct 2026). Shown on the admin O'Reilly page. -->

# O'Reilly Radar Newsletter Summary

*Summary of ~151 O'Reilly Radar newsletters received since subscribing on 30 April 2026 (via Substack). Roughly one article per weekday, plus weekly and monthly digests.*

---

## 📬 Regular Series

| Series | Frequency | What it covers |
|--------|-----------|----------------|
| **This Week in AI** | Weekly (Fridays) | News round-up. Recent editions: *Agents Are Outrunning the Systems Around Them* (2 Oct — cyberattacks, power constraints and consumer agents straining supporting systems), *AI's Safety Problem* (25 Sep), *Capability, Capital, and Consequences* (18 Sep), *The Frontier Is Getting Bigger* (4 Sep) |
| **Radar Trends to Watch** | Monthly | Cross-discipline trend round-up — May through **September 2026** editions, spanning AI models, security, infrastructure/ops, policy & governance, quantum, biology, robotics and web |
| **Generative AI in the Real World** | ~Weekly podcast | Ben Lorica interviews: Pete Warden (local voice AI, TinyML), Ben Miller (AI for real estate), Dan Guido / Trail of Bits, Chelsea Troy, Maarten Grootendorst, Chang She, DJ Patil, Harper Carroll |
| **Zero to Agent in 30 Minutes** | Build-along series | Running weekly: first agent with MCP; give your agent its own computer (sandboxed VMs); sports concierge (Chester Ismay); shared knowledge base across agents (Sajal Sharma); supply chain for agent context via APM (Maxim Salnikov); content engine (Max Johnson); financial news agent (Jayeeta Putatunda) |

---

## 🔑 Major Themes

### 1. Agentic Software Development *(the dominant theme)*
Addy Osmani's essay series anchors this thread: **The New Software Lifecycle**, **Agentic Code Review**, **Loop Engineering**, **Long-Running Agents**, **Agent Skills**, and **The Intent Debt**. Supporting pieces argue that **Coding Was Never a Bottleneck**, that agents need clear specs — but with a stopping rule (**When AI Writes the Code, Specifications Need an Exit Strategy**). Verification is the new hard part (**The Frontend Verification Gap**, **Evaluating AI-Generated Frontend Code: What Should We Actually Test?**, **AI Code Review Only Catches Half of Your Bugs**). A notable late addition: **Coding Agents Love Decision Records** (Duncan Davidson) — ADRs as durable context for agents, and **The Future of Software May Be Conversational Rather Than Autonomous** (Robert Englander) pushing back on full autonomy.

### 2. The Software Factory
What happens when agent-generated code becomes the default production mode: Addy Osmani's **Software Factories, Light and Dark**, **Inside a Software Factory** (vibe coding to clean, maintainable output), **What a User Story Actually Costs in a Dark Code Factory** (François-Xavier Martin, on unit economics when humans leave the loop), and **Architectural Guardrails for AI-Generated Code** (Theo Valmis).

### 3. MCP & Agent Interoperability *(fast-growing thread)*
**MCP Is Not Just Another API Standard** (what Model Context Protocol actually changes for agentic systems, and what it doesn't), **Effective Patterns for Advanced MCP Usage**, **The Interfaces Are Arriving** (agent interoperability standards), and the build-along **Zero to Agent: Build Your First Agent with MCP** (turning existing APIs into agent-usable tools).

### 4. Non-Human Identity & Agent Governance
Tushar Badlani and Mohit Bansal's two-parter remains the most directly transferable material to regulated environments: **Shadow Agents, Standing Privileges, and the Governance Gap Between Deployment and Discovery** and **The Identity Crisis No One Planned For**. Extended by **Operating Mode as Runtime State: A Contract for Enterprise** (explicit organisational state to avoid exception drift), **Principal Drift in Practice**, and **When Guardrails Go Wrong**.

### 5. Naming the Discipline
**What the Hell Is a Loop, Anyway?**, **We Keep Renaming AI Coding. Here's What I'd Call It.**, **What's an Orchestrator—and Why Does Software Need One?**, and **Why "It Depends" Is the Most Future-Proof Phrase in Software**.

### 6. Prompt Debt & Cost Discipline
**The Problem Is Prompt Debt** and Tim O'Reilly's **Prompt Debt and "Fighting the Weights"** — both bracketing the *Escaping the Prompt Debt Trap* session you attended. Extended by **Tokens Aren't Dollars**.

### 7. Context, Memory & Knowledge
**Why Doesn't Anyone Teach Developers About Context Management?**, **Your AI Agent Already Forgot Half of What You Told It**, **When Context Collapses**, **Context as Code**, **A Home for Personal Context**, and **Architecting for the Knowledge You Can't Capture** (designing and evaluating for tacit knowledge — the hardest requirement in enterprise AI).

### 8. AI Security
**The Base Is Under Attack**, **Prompt Injection to Data Exfil in 3 Hops**, **Beyond Prompt Injection**, **Who Authorized That? The Delegation Problem in Multi-Agent AI**, **When an Agent Deletes the Production Database**, and **Predict, Don't Enumerate**.

### 9. Agent Economics, Ops & Governance
**The Meter Was Always Running**, **The Economics of Agentic AI: Engineering for Imperfection**, **The Subsidy Ended**, **The Agentic P&L**, **Don't Neglect the Operational Groundwork**, **The Case Against Building Your Own Agent Platform**, **Fighting Tool Sprawl**, **Get a Good Return on Your AI Investments** (Sam Newman × DORA), **The Organization Is the Bottleneck**, and **Managers Are Not Overhead**.

### 10. Data Architecture *(expanded, September)*
**From Raw Data to Graph-Native AI** (why graph modelling deserves as much attention as GraphRAG and graph foundation models), **Navigating the Modern Data Lexicon: A Working Vocabulary for the Semantic Era**, **Enterprise Analytics Beyond Dashboards: Intelligent Data Orchestration with LLMs**, **A Data Center Is a Dependency Graph Before It Is a Building**, **Data Intelligence**, and **Your AI Problem Is a Data Problem**.

### 11. Model Internals
A three-part arc: **Introduction to Post-training**, **The Two Pillars of Post-training: Reinforcement Learning and Supervised Fine-Tuning**, and **The Post-training Process OpenAI Used for ChatGPT**.

### 12. Open Source, Sovereignty & Trust
Tim O'Reilly's **Why Open Source Matters for AI**, Raffi Krikorian's counterpoint **Is Open-Source AI Really the Dangerous Path?**, Nicole Butterfield's **AI Sovereignty: Bargaining with Big Tech and the Promise of Full Stack Open Source AI**, **When Content Is Free, Trust Is the Product**, **Hey AI, Can You Just Give Me a Hat Tip Please?** (attribution and compensation), and **When Software Subscriptions Become Public Policy**.

### 13. Big-Picture Commentary *(Tim O'Reilly, Mike Loukides & guests)*
**Superpowers for Humans** (Tim O'Reilly's written companion to the Jesse Vincent session you attended), **What AI Can Teach Us About Being Human**, **LLMs Reward Expertise** (Sean Goedecke), **Not About Navier-Stokes** (using AI productively), **The End of Tokenmaxxing**, **Burnout and Cognitive Debt**, **The Agent-Era Career**, **Ordinary Engineers, Not Heroic Inventors**, **How AI Swarms Are Disrupting Democracy**, and **Experience Mapping Matters More the Faster You Move** (Jim Kalbach).

---

## ⭐ Your Starred Radar Articles

You've starred roughly half the Radar output — heavily clustered around **agentic coding practice** (*Coding Agents Love Decision Records*, *The Intent Debt*, *Evaluating AI-Generated Frontend Code*, *Architectural Guardrails for AI-Generated Code*), **MCP and interoperability** (*MCP Is Not Just Another API Standard*, *The Interfaces Are Arriving*), **agent governance** (*Operating Mode as Runtime State*, *Shadow Agents, Standing Privileges…*), **data architecture** (*Navigating the Modern Data Lexicon*, *A Data Center Is a Dependency Graph*), and **strategy** (*Superpowers for Humans*, *LLMs Reward Expertise*, *AI Sovereignty*). This mirrors your live-event attendance almost exactly — agents, security, architecture and engineering leadership.

---

*Newsletter archive: all articles are also available at the O'Reilly Radar Substack, linked from each email.*

---

## 📄 Appendix — CV snippet (Education / Training)

> **Continuous Professional Development — O'Reilly Media (2024–present).** Completed 43 instructor-led technical training events covering agentic AI, AI-assisted software development, AI security and governance, software architecture and engineering leadership. Sustained by close reading of O'Reilly Radar, the publisher's practitioner research and commentary series, with a focus on the evaluation, traceability and control of AI-assisted systems in regulated settings.
