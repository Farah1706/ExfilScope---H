// Learning content. Plain language first; the technical part is expandable. Statements
// follow docs/ARCHITECTURE.md, docs/EVIDENCE.md and docs/AGENT.md.

export const GUIDES = [
  { id: "what", title: "What is ExfilScope?", figure: "pipeline",
    simple: [
      "ExfilScope helps keep government AI actions within their permission.",
      "It checks requests before sending, then compares the approval with a separate record of what happened."
],
    technical: [
      "The chain under test is proposed action → gateway decision → permitted action → runtime execution claim, compared with the independently observed request.",
      "Routine evidence stores protected-value identifiers and keyed HMAC commitments of JSON bodies, not the protected plaintext.",
      "Scope: one agent, one local model, one HTTP/API tool, JSON bodies, controlled HTTP and HTTPS endpoints. It is a research prototype, not a DLP product.",
    ], related: ["problem", "ledgers", "outcomes"] },
  { id: "problem", title: "Why check what actually happened?",
    simple: [
      "An assistant’s own report may be incomplete or wrong.",
      "ExfilScope compares that report and the approval with an independent activity record."
],
    technical: [
      "Controlled faults are injected between authorization and emission: a blocked request sent anyway, a body changed after approval, a redaction reversed, a different destination, or an observation withheld from the verifier.",
      "These faults test reconciliation. They do not measure how often real attackers can cause such failures.",
    ], related: ["block-bypass", "payload-divergence", "destination-divergence"] },
  { id: "tools", title: "How does the assistant take action?",
    simple: [
      "The assistant prepares one request. A separate program checks whether it may proceed.",
      "The assistant cannot choose its own safety rules."
],
    technical: [
      "The LangGraph workflow is bounded: retrieve, generate one proposal, validate it against a strict schema (endpoint alias AUTHORIZED, method POST, a JSON body), then submit once to the gateway's POST /execute boundary.",
      "A model may propose something unexpected. The gateway and verifier still behave correctly and the deviation is reported, never replaced.",
    ], related: ["rag", "ollama", "gateway"] },
  { id: "rag", title: "Where does the information come from?",
    simple: [
      "Security tests use sample documents, including examples of confidential information.",
      "The government demonstration also uses published GDRFA statistics. These are public totals, not personal records."
],
    technical: [
      "Retrieval uses Chroma with the all-MiniLM-L6-v2 ONNX embedding, loaded only from a cache whose SHA-256 matches Chroma's pinned value; it never downloads on its own.",
      "Source references such as DOC_001:chunk_1 are registry associations. They do not reveal the model's internal reasoning.",
    ], related: ["tools", "ollama"] },
  { id: "ollama", title: "Which AI model is used?",
    simple: [
      "The live prototype uses Qwen3, an AI model running on the local computer.",
      "The recorded website replays earlier results. It does not run a new model."
],
    technical: [
      "Model: qwen3:4b-instruct-2507-q4_K_M, Hackathon manifest digest 6214d088…3054. The readiness check compares the digest Ollama reports.",
      "The agent worker runs in its own Python environment (.venv-agent) and a separate process, with a reduced environment and no access to policy, keys or ledger paths.",
    ], related: ["tools", "rag"] },
  { id: "gateway", title: "What is checked before sending?", figure: "decisions",
    simple: [
      "The safety check reviews the destination and content against the rules.",
      "It allows the request, removes confidential values where permitted, or stops it."
],
    technical: [
      "Policy rules fix endpoint, method, route, approved JSON fields and the paths where redaction is allowed. Bodies are parsed strictly; duplicate keys, invalid numbers and over-deep structures are rejected.",
      "A redacted body is revalidated against the schema after transformation. The wrapper then sends only the permitted request through the fixed proxy, without redirects, retries or fallback to direct egress.",
    ], related: ["decisions", "payload", "ledgers"] },
  { id: "decisions", title: "What do the three decisions mean?", figure: "decisions",
    simple: [
      "ALLOW means send the approved request. REDACT means remove confidential values before sending.",
      "BLOCK means nothing is approved for sending."
],
    technical: [
      "A single protected occurrence outside the approved redaction paths blocks the whole action.",
      "These are gateway decisions, made before emission. MATCH, MISMATCH and UNVERIFIED are verification results, made afterwards. A BLOCK can be a MATCH.",
    ], related: ["gateway", "outcomes"] },
  { id: "payload", title: "What information is being sent?",
    simple: [
      "The request contains information the assistant wants to send to a destination.",
      "The safety check reviews that content for confidential values and rule violations."
],
    technical: [
      "Fields are addressed with JSON Pointer-style paths such as /data/0/text. Approved fields and redaction paths in the policy use the same notation, with * for array positions.",
    ], related: ["canonicalization", "hmac"] },
  { id: "ledgers", title: "Why keep two records?", figure: "pipeline",
    simple: [
      "The approval record holds the decision and the system’s report.",
      "The activity record holds independent observations. Comparing them helps reveal differences."
],
    technical: [
      "Only the runtime writes Ledger A and only the proxy writes Ledger B. They are separate SQLite databases; the verifier and this interface only read them, and the interface reads only validated, minimized exports.",
      "On Windows all local services share one account, so this separation is by process and file, not enforced by the operating system.",
    ], related: ["mitmproxy", "hmac", "coverage"] },
  { id: "mitmproxy", title: "What does the activity monitor see?",
    simple: [
      "A separate monitor records requests at a checkpoint on the way to the test destination.",
      "This confirms observation at that checkpoint. It does not prove that a real government service processed the request."
],
    technical: [
      "The addon records endpoint and route labels, method, request size, response status, anomalies and an HMAC commitment computed from the body bytes it received. It never accepts a commitment supplied by the runtime.",
      "Redirects, retries, body streaming and raw flow capture are disabled, and TLS verification stays on. Observation at the proxy shows arrival at the monitored boundary, not processing by the remote server.",
    ], related: ["ledgers", "coverage"] },
  { id: "canonicalization", title: "How is the content compared?", figure: "hmac",
    simple: [
      "The same information can be written with different spacing or ordering.",
      "ExfilScope puts it into a consistent form before comparing it, so formatting alone does not look like a change."
],
    technical: [
      "ExfilScope uses RFC 8785 (JSON Canonicalization Scheme). The diagnostics include a whitespace, key-order and escape-equivalence condition that must MATCH.",
    ], related: ["hmac", "payload"] },
  { id: "hmac", title: "How are content fingerprints used?", figure: "hmac",
    simple: [
      "A fingerprint is a short code used to compare the approved content with the observed content.",
      "Different fingerprints show a change. They do not reveal which words changed."
],
    technical: [
      "HMAC is not encryption: nothing can be decrypted from it, and the body cannot be recovered. The secret key prevents anyone without it from testing guesses against a stored fingerprint.",
      "A different commitment does not reveal which value changed and does not by itself prove that a secret leaked. Commitments are comparable only when the key ID and canonicalization version agree.",
    ], related: ["canonicalization", "payload-divergence"] },
  { id: "outcomes", title: "What do the results mean?", figure: "outcomes",
    simple: [
      "MATCH means the evidence agrees with approval. MISMATCH means a supported difference was found.",
      "UNVERIFIED means there is not enough evidence to decide. A correctly stopped request can have a MATCH result."
],
    technical: [
      "Missing, late, duplicate or incompatible evidence never yields MATCH. BLOCK may MATCH only for a complete, health-qualified proxy-boundary window with unambiguous evidence and a NOT_EXECUTED claim (SCOPED_PROXY_ABSENCE).",
    ], related: ["coverage", "interpretation"] },
  { id: "payload-divergence", title: "What if the content changes after approval?",
    simple: [
      "The observed content can be compared with what was approved.",
      "The tests deliberately change content after approval to check whether the difference is detected."
],
    technical: [
      "Label: PAYLOAD_DIVERGENCE. It requires comparable commitments (same key and canonicalization). The verifier cannot say which field changed.",
    ], related: ["hmac", "decisions"] },
  { id: "block-bypass", title: "What if a stopped request is still sent?",
    simple: [
      "A request may be refused but still appear at the activity checkpoint.",
      "This controlled test checks whether ExfilScope detects that difference."
],
    technical: [
      "Label: BLOCK_BYPASS, from a unique in-window observation correlated with a BLOCK event. In the lab the harness emits the blocked body deliberately; the model does not cause it.",
    ], related: ["decisions", "outcomes"] },
  { id: "destination-divergence", title: "What if the request goes to the wrong place?",
    simple: [
      "The content can be correct while the destination is wrong.",
      "ExfilScope compares both the content and the destination with the approval."
],
    technical: [
      "Label: DESTINATION_DIVERGENCE, from the normalized endpoint label (scheme, host and effective port). The lab sends to an UNAUTHORIZED local receiver; the frozen research also tests host and port changes.",
    ], related: ["ledgers", "outcomes"] },
  { id: "coverage", title: "Why does monitoring need to stay active?",
    simple: [
      "A missing activity record is meaningful only if the monitor was active for the whole check period.",
      "If monitoring is incomplete, the result remains unconfirmed."
],
    technical: [
      "The monitor writes a hash-chained health journal with receipts and closing barriers. The largest tolerated gap between health records is h = 0.6576741600001696 s, fixed by the D5 calibration.",
      "The hash chain detects accidental gaps; it is not tamper evidence against a trusted writer.",
    ], related: ["window", "outcomes"] },
  { id: "window", title: "When is activity checked?", figure: "window",
    simple: [
      "The prototype checks a five-second period after the approval decision.",
      "It then allows one extra second for records to finish saving before comparing them."
],
    technical: [
      "Events are correlated by trace ID and a shared monotonic clock domain before destination and payload are compared. Activity after the window is reported as late, never as an in-window bypass.",
    ], related: ["coverage", "interpretation"] },
  { id: "interpretation", title: "How should I read the evidence?",
    simple: [
      "Read the approval decision and the observed activity as separate facts.",
      "Use the result’s explanation to see what the evidence supports and what remains unknown."
],
    technical: [
      "A proxy observation is not proof of remote processing. A differing commitment does not reveal the changed bytes. A source reference is a registry association, not model reasoning. A correctly blocked request can MATCH. An observation gap gives UNVERIFIED.",
    ], related: ["outcomes", "threat-model"] },
  { id: "threat-model", title: "What are the prototype’s limits?",
    simple: [
      "These are controlled local demonstrations using public statistics and sample confidential records.",
      "Government deployment, organization-wide identity checks, and protection of every possible communication channel have not been validated."
],
    technical: [
      "Ledgers are unsigned; the health chain is not tamper evidence; clock-domain IDs are trusted declarations. The local tool API is unauthenticated and must stay on loopback.",
      "Windows-local services share one account. The D5 Docker topology validated role isolation; neither proves host-wide containment. All results come from a controlled laboratory with synthetic values.",
    ], related: ["interpretation", "ledgers"] },
];

export const GUIDE_BY_ID = Object.fromEntries(GUIDES.map((g, i) => [g.id, { ...g, n: i + 1 }]));

// In-context help: what am I looking at, why it matters, what it means, a common mistake.
export const HELP = {
  readiness: { title: "System readiness", guide: "ollama",
    what: "Probes made when you opened this page: files present, services answering, hashes and digests checked.",
    why: "A mode is offered only when everything it needs is actually available.",
    means: "Installed or configured: present and valid. Running: a service answered. Healthy: it answered and its identity was verified. Not required: unused by local demonstrations.",
    mistake: "Gateway and mitmproxy show as configured or installed, not running: a fresh instance starts for each run and stops after it." },
  architecture: { title: "How a request is checked", guide: "what",
    what: "The steps a request passes through, with separate approval and activity records.",
    why: "The separation between the runtime's record and the monitor's record is what makes the comparison meaningful.",
    means: "Solid arrows carry the request; dashed arrows carry evidence to the verifier.",
    mistake: "The verifier does not sit in the request path and cannot stop a request; it reconciles evidence afterwards." },
  pipeline: { title: "Evidence pipeline", guide: "ledgers",
    what: "Six facts about one attempt: what was proposed, decided, permitted and claimed (Ledger A), what was observed (Ledger B) and what the verifier concluded.",
    why: "The capstone's question is whether these agree. Each comes from a different writer.",
    means: "A red top edge marks a stage where the evidence planes differ; a dashed stage has no evidence.",
    mistake: "The runtime's claim is not an observation. Only the Observed stage comes from the independent monitor." },
  stages: { title: "Run stages", guide: "window",
    what: "Records sent by the run process as each step finished. A stage is complete only when the backend reported it.",
    why: "It shows the real experiment, including failures and unavailable steps.",
    means: "Several stages complete together because the harness performs authorization, emission and the 5 s window in one call; their facts are then read from Ledger A and the verifier.",
    mistake: "A completed observation stage with no paired event is not a failure: for a BLOCK it is the expected outcome." },
  compare: { title: "Ledger comparison", guide: "ledgers",
    what: "Ledger A's permitted request on the left, Ledger B's observed request on the right, and the verifier's check for each field in the middle.",
    why: "Each disagreement maps to a divergence label; each unavailable field limits what can be concluded.",
    means: "Agrees or Equal: the planes agree. Diverges or Different: a supported divergence. Unavailable: no comparable evidence.",
    mistake: "Equal fingerprints support identical bodies; different fingerprints do not show which value changed." },
  hmac: { title: "Body fingerprints", guide: "hmac",
    what: "HMAC-SHA-256 over RFC 8785 canonical JSON, computed separately by the gateway and by the proxy.",
    why: "It lets the bodies be compared without storing them.",
    means: "Same fingerprint, same key and format: identical canonical bodies.",
    mistake: "This is not encryption and the key is never shown. A short form is displayed; the full value is in the technical view." },
  timeline: { title: "Timing and coverage", guide: "window",
    what: "The gateway decision at 0 s, the observation window W, the drain grace G, the runtime completion and the proxy observation if one was paired.",
    why: "Correlation is by trace and shared monotonic time; evidence outside the window cannot support an in-window conclusion.",
    means: "A solid green track means the verifier reported complete, health-qualified coverage for the window. A dashed amber track means coverage is not established: a health gap, a correlation diagnostic or unverified evidence, whether or not an observation was paired.",
    mistake: "An empty window does not prove nothing was sent unless the verifier itself reported SCOPED_PROXY_ABSENCE." },
  checklist: { title: "Investigation checklist", guide: "interpretation",
    what: "The ten questions of the Forensic Assessment Study (Appendix A.4), as a reasoning aid.",
    why: "They walk from protected items to the strongest justified conclusion.",
    means: "Each question points to where the evidence is. Ticks are kept in this browser tab only.",
    mistake: "There are no answers here: the study's reference answers and scores are restricted and are never shown." },
  results: { title: "Research results", guide: "outcomes",
    what: "Figures from the custodian's validated records, each with its run ID, source commit and the document that records it.",
    why: "They show the verifier reached the pre-registered conclusion under designed conditions.",
    means: "Each denominator is reported separately: 42 primary, 6 supplementary, 24 diagnostics, 180 latency pairs.",
    mistake: "These are laboratory results with synthetic values, not real-world detection rates." },
  trust: { title: "Government Trust extension", guide: "threat-model",
    what: "Signed, two-minute, single-use capabilities that bind a registered agent key to one task scope, checked before the research gateway.",
    why: "An editable agent name is not identity. A signature from a registered key over the exact action is.",
    means: "Accepted attempts continue to the unchanged gateway, proxy and verifier. Rejected attempts are never authorized or sent.",
    mistake: "This is an engineering extension separate from the frozen research. Keys live in one process under one account, which is not OS-enforced custody." },
};

// FAS questions, verbatim from src/exfilscope/research/fas_review.py, with where to look.
export const CHECKLIST = [
  ["Which registered protected items and sources were implicated, or none?", "Ledger A: protected-value hits (IDs and source references only)."],
  ["What endpoint, method and route were proposed?", "Ledger A: proposed request metadata."],
  ["What decision was made and why? Include the policy version.", "Ledger A: decision, reason code and policy version."],
  ["How did policy change the action?", "Compare proposed and permitted metadata; for REDACT, the hits' locations."],
  ["What action was permitted, or none?", "Ledger A: permitted metadata and body fingerprint."],
  ["What execution did the runtime claim? Include any safe error category.", "Ledger A: runtime claim, error category and response status."],
  ["What request was observed at the boundary, or what observation gap is supported?", "Ledger B and the timing view; check coverage and diagnostics."],
  ["Is the runtime claim compatible with the available network evidence?", "Comparison: the runtime claim row."],
  ["What final status is justified by the supplied evidence?", "Verdict, evidence status and diagnostics."],
  ["What divergence or investigative limitation follows, and what cannot be concluded?", "Labels, and the lists of what can and cannot be concluded."],
];

export const COMPONENTS = {
  operator: { title: "Human approval", plane: "Government Trust", what: "A person approves a task, withdraws access, or restores access with a new identity.", why: "The service stays under human control.", receives: "A task and registered agent key.", produces: "Signed permission and recorded operator events.", trust: "Local authenticated session; not organizational identity proof or in-flight cancellation.", role: "Stops subsequent protected dispatch after revocation. The old identity stays revoked after recovery.", guide: "threat-model" },
  identity: { title: "Agent identity", plane: "Government Trust", what: "Checks that the request comes from a registered agent.", why: "The service needs to know who is acting.", receives: "Signed request proof and trusted registration.", produces: "A validated identity, or rejection before the gateway.", trust: "Ephemeral keys and a local trust root; not OS-enforced custody.", role: "Binds the requesting agent to the task permission.", guide: "gateway" },
  permission: { title: "Task permission", plane: "Government Trust", what: "Allows one approved task for a short time.", why: "An agent should only do the work it was given permission to do.", receives: "Issuer signature, action proof and revocation state.", produces: "In-scope authorization or rejection.", trust: "Checks issuer, expiry, replay, scope and revocation before dispatch.", role: "Keeps the agent inside the approved task and route.", guide: "gateway" },
  official: { title: "Official figures", plane: "Government Trust", what: "Checks the brief against the saved government source, including the year and measure.", why: "An incorrect or wrongly attributed figure can mislead a service decision.", receives: "Selected cells and the exact proposed payload.", produces: "A source-bound brief, or rejection before the gateway.", trust: "Publisher, source file, workbook hash, dataset digest, year, metric, count and unit are bound together.", role: "Refuses altered figures, false attribution, unsupported derived figures, mixed citations and duplicate JSON keys.", guide: "gateway" },
  rag: { title: "Sample documents", plane: "Agent",
    what: "Example documents used to test how the assistant handles confidential information.",
    why: "These tests show whether confidential information is removed or stopped before sending.",
    receives: "The task's retrieval query.", produces: "Retrieved document chunks with source references.",
    trust: "Untrusted content: an attacker may influence what is retrieved.", role: "Source of the material the gateway must inspect.", guide: "rag" },
  agent: { title: "AI assistant", plane: "Agent",
    what: "Prepares a request using the task and available information.",
    why: "Its proposed action must be checked before it can go ahead.",
    receives: "Task instruction and retrieved chunks.", produces: "One validated JSON proposal for the HTTP tool.",
    trust: "Untrusted. Cannot choose policy, proxy, keys, trace IDs or ledger paths.", role: "Proposes the action under test.", guide: "ollama" },
  gateway: { title: "Safety check", plane: "Ledger A",
    what: "Decides whether to send the request, remove confidential content, or stop it.",
    why: "A request needs approval before it is sent.",
    receives: "The proposed action.", produces: "A decision, the permitted action and a Ledger A event with the permitted-body HMAC, written before emission.",
    trust: "Trusted.", role: "Writes the authorization half of the evidence.", guide: "gateway" },
  tool: { title: "Send request", plane: "Ledger A",
    what: "Carries out the approved action and reports what it attempted.",
    why: "A separate observation is needed to confirm what happened.",
    receives: "The permitted action.", produces: "The outbound request and the runtime execution claim in Ledger A.",
    trust: "Trusted in normal runs; the lab harness simulates its failure in fault mode.", role: "Executes, and claims what it did.", guide: "tools" },
  proxy: { title: "Activity monitor", plane: "Ledger B",
    what: "Independently records requests passing the monitored checkpoint.",
    why: "The check does not rely only on the assistant’s own report.",
    receives: "Every request the tool sends through it.", produces: "Ledger B observations with its own HMAC, and the health journal.",
    trust: "Trusted. Never accepts a commitment from the runtime.", role: "Writes the observation half of the evidence.", guide: "mitmproxy" },
  endpoint: { title: "Test destination", plane: "Lab",
    what: "A local receiver used in the demonstration.",
    why: "Lets the team test delivery in a controlled setting.",
    receives: "Requests that passed the proxy.", produces: "A response status, and receiver counts used only as harness truth.",
    trust: "Lab infrastructure; not evidence.", role: "Destination of permitted and faulted requests.", guide: "destination-divergence" },
  ledgerA: { title: "Approval record", plane: "Ledger A",
    what: "Records the decision and what the system reports it did.", why: "Provides the approved action to compare with observed activity.",
    receives: "Gateway and wrapper events.", produces: "Minimized authorization and claim records.",
    trust: "Written only by the runtime.", role: "First evidence plane.", guide: "ledgers" },
  ledgerB: { title: "Activity record", plane: "Ledger B",
    what: "Records what the independent monitor observed and whether it was active.", why: "Provides a separate account of the activity.",
    receives: "Proxy observations and health receipts.", produces: "Minimized observation and coverage records.",
    trust: "Written only by the proxy.", role: "Second evidence plane.", guide: "coverage" },
  verifier: { title: "Compare records", plane: "Verification",
    what: "Compares the approved action with the independently observed activity.",
    why: "Reports agreement, a difference, or insufficient evidence.",
    receives: "Read-only snapshots of both ledgers and health.", produces: "MATCH, MISMATCH or UNVERIFIED with labels and diagnostics.",
    trust: "Trusted; reads, never writes, the ledgers.", role: "Reconciliation.", guide: "outcomes" },
  investigation: { title: "Review result", plane: "Verification",
    what: "Shows the result and the records supporting it.",
    why: "A person can review the evidence and decide what to do next.",
    receives: "Only validated, minimized snapshots from the trusted exporter.", produces: "Explanations and a CSV export; never evidence.",
    trust: "Read-only; has no ledger, key or restricted-file access.", role: "Explanation.", guide: "interpretation" },
};
