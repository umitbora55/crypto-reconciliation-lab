"use strict";
(() => {
  const data = window.PROVENANCE_DATA;
  const byId = id => document.getElementById(id);
  const el = (name, text, className) => {
    const node = document.createElement(name);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };
  const value = item => item === null || item === undefined ? "Not reported" : String(item);
  const parse = text => { try { return JSON.parse(text); } catch (_) { return null; } };
  const pretty = item => JSON.stringify(item, null, 2);
  const tag = (text, tone="neutral") => el("span", text, "tag " + tone);
  const details = (title, item) => {
    const box = el("details"); box.append(el("summary", title), el("pre", pretty(item))); return box;
  };
  const field = (list, label, content, code=false) => {
    list.append(el("dt", label)); const dd = el("dd"); dd.append(el(code ? "code" : "span", value(content))); list.append(dd);
  };
  const notice = (text, bad=false) => el("p", text, "notice" + (bad ? " error" : ""));
  const hexBytes = text => {
    if (typeof text !== "string" || !/^(?:[0-9a-f]{2})*$/.test(text)) return null;
    const result = new Uint8Array(text.length / 2);
    for (let i=0; i<result.length; i++) result[i] = parseInt(text.slice(i*2, i*2+2), 16);
    return result;
  };
  if (!data || !data.run || !data.capture || !data.report) {
    byId("finding-detail").replaceChildren(notice("The local view data is unavailable. Use the independent CLI to inspect this package.", true)); return;
  }
  const run = data.run, capture = data.capture, report = data.report;
  const tables = capture.tables || {}, evidence = run.evidence || {};
  const rows = table => Array.isArray(tables[table]) ? tables[table] : [];
  const materials = data.materials || {};
  let selected = -1;
  let lineUrl = null;
  const hasMaterial = path => Object.hasOwn(materials, path);
  const download = (path, label) => {
    const link = el("a", label);
    if (!/^(?:materials\/(?:snapshots|envelopes|policies)\/)[0-9a-f]{64}\.(?:json|jsonl)$/.test(path) || !hasMaterial(path)) return el("span", label + " — unavailable", "muted");
    link.href = "./" + path.split("/").map(encodeURIComponent).join("/");
    link.download = path.split("/").pop();
    link.dataset.material = path;
    return link;
  };
  const materialIdentity = path => {
    const item = materials[path];
    return item ? `${item.bytes} exact bytes · SHA-256 ${item.sha256}` : "Full original material was not supplied.";
  };
  const latest = rows("auth_policy_activations").reduce((best, row) => !best || row.epoch > best.epoch ? row : best, null);
  const policyAt = hash => rows("auth_policy_snapshots").find(row => row.policy_hash === hash);
  const headPolicy = latest ? parse((policyAt(latest.policy_hash) || {}).payload) : null;
  const isProtected = rows("auth_configuration").length > 0;
  byId("run-id").textContent = report.run_id;
  byId("balance-at").textContent = run.balance_at;
  byId("knowledge-at").textContent = run.knowledge_at;
  const captureSummary = byId("capture-summary");
  field(captureSummary, "Capture profile (observed)", report.capture_profile);
  field(captureSummary, "Capture digest", report.capture_digest, true);
  field(captureSummary, "Original run byte SHA-256", report.run_payload_sha256, true);
  field(captureSummary, "Database byte SHA-256", capture.database && capture.database.sha256, true);
  field(captureSummary, "Policy head in this capture", latest ? "Epoch " + latest.epoch : "No auth history recorded");
  field(captureSummary, "Source verification", "NOT_PERFORMED by this page");

  function showOrigin(receipt) {
    const box = byId("origin-detail"); box.replaceChildren();
    byId("origin-section").hidden = false;
    const effects = rows("delivery_effects").filter(row => row.core_receipt_id === receipt.id);
    if (!effects.length) {
      box.append(notice(isProtected ? "Protected receipt has no observed original delivery effect. The independent verifier must reject an inconsistent protected link." : "Unsigned legacy receipt: no signed admission relationship is recorded.", isProtected));
      box.append(details("Observed physical receipt", receipt));
      byId("origin-title").focus(); return;
    }
    if (effects.length !== 1) box.append(notice("More than one original effect points to this candidate. This view does not resolve that inconsistency.", true));
    for (const effect of effects) {
      const links = rows("auth_delivery_links").filter(row => row.stream_id === effect.stream_id && row.sequence === effect.sequence);
      const decision = links.length === 1 ? rows("auth_decisions").find(row => row.id === links[0].decision_id) : null;
      const endorsement = decision ? rows("auth_endorsements").find(row => row.id === decision.endorsement_id) : null;
      const currentKey = endorsement && headPolicy ? headPolicy.keys.find(row => row.key_id === endorsement.key_id) : null;
      const summary = el("div", null, "path-summary");
      for (const [label, text] of [["Physical receipt", "Local row " + receipt.id], ["Original effect", effect.stream_id + " / line " + effect.sequence], ["Original policy", decision ? "Epoch " + decision.epoch + " · " + decision.decision : "No original auth link"]]) {
        const card = el("div"); card.append(el("span", label, "label"), el("strong", text)); summary.append(card);
      }
      box.append(summary);
      if (!isProtected) box.append(notice("Unsigned legacy delivery: the financial receipt is observable, but no protected source signature or policy link is recorded."));
      if (isProtected && (!decision || !endorsement)) box.append(notice("The protected original decision/endorsement relationship is missing or inconsistent. This is not a legacy fallback.", true));
      if (endorsement) {
        const list = el("dl");
        field(list, "Publisher", endorsement.source);
        field(list, "Signing key", endorsement.key_id);
        field(list, "Original acceptance", "Decision " + decision.id + ", epoch " + decision.epoch + ", key " + decision.current_key_status);
        field(list, "Key at the observed capture head", currentKey ? currentKey.status + " (epoch " + latest.epoch + ")" : "Not available");
        field(list, "Run creation authorization cut", "NOT_RECORDED — this capture does not establish which physical candidate existed when the run was saved.");
        box.append(list);
        if (currentKey && currentKey.status === "revoked") box.append(notice("The key is revoked at the capture head. Its original recorded acceptance belongs to an earlier policy epoch; current status does not replace that original decision."));
      }
      box.append(el("h4", "Exact captured source line"));
      const line = hexBytes(effect.payload);
      if (line) {
        let lineText;
        try { lineText = new TextDecoder("utf-8", {fatal:true}).decode(line); }
        catch (_) { lineText = "The stored bytes are not valid UTF-8. Inspect the raw bytes; the verifier decides validity."; }
        const label = el("p", "One-based file line " + effect.sequence + " · includes its terminal LF", "line-label");
        const code = el("pre", lineText); code.dataset.sourceLine = "true";
        box.append(label, code, el("p", line.length + " exact bytes · SHA-256 " + effect.payload_sha256, "identity"));
        const downloads = el("div", null, "downloads");
        if (lineUrl) URL.revokeObjectURL(lineUrl);
        lineUrl = URL.createObjectURL(new Blob([line], {type:"application/octet-stream"}));
        const lineDownload = el("a", "Download exact line bytes");
        lineDownload.href = lineUrl; lineDownload.download = "source-line-" + effect.sequence + ".jsonl"; lineDownload.id = "download-line";
        downloads.append(lineDownload);
        if (endorsement) {
          const snapshotPath = "materials/snapshots/" + endorsement.snapshot_hash + ".jsonl";
          downloads.append(download(snapshotPath, "Download full signed snapshot"));
          box.append(downloads, el("p", materialIdentity(snapshotPath), "identity"));
          if (!hasMaterial(snapshotPath)) box.append(notice("MISSING_SIGNED_SNAPSHOT: the full original signed file was not supplied. A captured line or prefix cannot stand in for the full snapshot. Financial values above remain the saved values."));
        } else box.append(downloads);
      } else box.append(notice("The captured effect has no readable exact payload bytes.", true));
      if (endorsement) {
        const signature = el("details"); signature.append(el("summary", "Signature, original policy and full raw materials"));
        const hashes = el("dl");
        field(hashes, "Endorsement ID", endorsement.id, true);
        field(hashes, "Public key fingerprint", endorsement.fingerprint, true);
        field(hashes, "Signed statement SHA-256", endorsement.statement_hash, true);
        field(hashes, "Original policy SHA-256", decision.policy_hash, true);
        field(hashes, "Capture head policy SHA-256", latest && latest.policy_hash, true);
        signature.append(hashes);
        const downloads = el("div", null, "downloads");
        downloads.append(download("materials/envelopes/" + endorsement.id + ".json", "Download original DSSE envelope"), download("materials/policies/" + decision.policy_hash + ".json", "Download original admission policy"));
        if (latest && latest.policy_hash !== decision.policy_hash) downloads.append(download("materials/policies/" + latest.policy_hash + ".json", "Download capture head policy"));
        signature.append(downloads);
        const statementBytes = hexBytes(endorsement.payload);
        if (statementBytes) signature.append(el("pre", new TextDecoder().decode(statementBytes)));
        box.append(signature);
      }
      const attempts = rows("delivery_attempts").filter(row => row.stream_id === effect.stream_id && row.sequence === effect.sequence);
      const attemptIds = new Set(attempts.map(row => row.id));
      const attemptLinks = rows("auth_attempt_links").filter(row => attemptIds.has(row.attempt_id));
      const decisionIds = new Set(attemptLinks.map(row => row.decision_id));
      const laterDecisions = rows("auth_decisions").filter(row => decisionIds.has(row.id));
      box.append(details("Observed attempts and replay decisions — original link remains separate", {attempts, attempt_links:attemptLinks, decisions:laterDecisions}));
      box.append(details("Original captured receipt / effect / auth link", {receipt, effect, original_links:links, original_decision:decision}));
    }
    byId("origin-title").focus();
  }

  function showReceipt(hash) {
    byId("receipt-section").hidden = false;
    byId("origin-section").hidden = true;
    const box = byId("receipt-detail"); box.replaceChildren();
    box.append(el("p", "Recorded receipt hash", "label"), el("code", hash));
    const candidates = rows("receipts").filter(row => row.receipt_hash === hash);
    box.append(el("p", candidates.length + " physical candidate" + (candidates.length === 1 ? "" : "s") + " in this observed capture", "small"));
    if (!candidates.length) box.append(notice("No physical candidate is present for this required saved hash. The independent verifier must reject incomplete listed evidence.", true));
    if (candidates.length > 1) box.append(notice("MULTIPLE_CANDIDATES: every observed physical row is listed. No candidate is declared the one used when this old run was created. Full physical binding remains ambiguous."));
    for (const candidate of candidates) {
      const button = el("button", "Inspect local physical row " + candidate.id + " · " + candidate.status, "candidate-button");
      button.type = "button"; button.dataset.receiptRow = String(candidate.id);
      button.addEventListener("click", () => showOrigin(candidate)); box.append(button);
    }
    if (candidates.length === 1) showOrigin(candidates[0]);
    else byId("receipt-title").focus();
  }

  function renderEvidence(id) {
    const item = evidence[id];
    if (!item) return notice("A listed evidence entry is missing: " + id, true);
    const record = item.record;
    const group = item.derived_correction_group;
    let label = record ? `${record.kind} · ${record.source} · ${record.scope || record.ref || record.batch_id || record.asset}` : group ? "Derived correction group" : item.quarantined_receipt ? "Quarantined receipt" : "Raw recorded receipt";
    if (record && record.version !== undefined) label += " · version " + record.version;
    const card = el("details"), summary = el("summary", label); card.id = "evidence-" + id; card.append(summary);
    const body = el("div", null, "record-body");
    body.append(el("p", "Evidence ID " + id, "identity"));
    if (record) {
      const meta = el("div", null, "record-meta");
      for (const key of ["stream", "amount", "balance_at", "occurred_at", "mode"]) {
        if (record[key] !== undefined) meta.append(el("span", key + ": " + value(record[key])));
      }
      body.append(meta);
    }
    if (group) {
      body.append(el("p", "This group is derived saved evidence, not a physical receipt. Follow its original correction and target records.", "help"));
      for (const key of ["correction_record_id", "target_record_id"]) {
        if (group[key]) {
          const button = el("button", "Open " + key.replaceAll("_", " "), "receipt-link");
          button.type = "button";
          button.addEventListener("click", () => {
            const target = byId("evidence-" + group[key]);
            if (target) {target.open = true; target.querySelector("summary").focus();}
          }); body.append(button);
        }
      }
    }
    const hashes = record ? item.receipt_ids || [] : group ? [] : [id];
    for (const hash of hashes) {
      const button = el("button", "Follow recorded receipt", "receipt-link");
      button.type = "button"; button.dataset.receiptHash = hash; button.append(el("code", hash));
      button.addEventListener("click", () => showReceipt(hash)); body.append(button);
    }
    body.append(details("Saved evidence JSON", item)); card.append(body); return card;
  }

  function chooseFinding(ordinal) {
    selected = ordinal;
    const finding = run.findings[ordinal];
    const heading = byId("finding-heading"); heading.replaceChildren();
    const title = el("div", null, "detail-heading"), name = el("div");
    name.append(el("p", "Comparison " + finding.comparison + " · " + finding.asset, "eyebrow"), el("h2", finding.scope === "customer_liability" ? "Customer liability and custody" : "Investor " + finding.scope));
    title.append(name, tag(finding.reconciliation_state, finding.reconciliation_state === "MISMATCH" ? "bad" : finding.reconciliation_state === "MATCHED" ? "good" : "warning"));
    heading.append(title, el("p", "Finding " + report.run_id + ":" + ordinal, "finding-id"));
    const amounts = byId("financial-summary"); amounts.replaceChildren();
    for (const [label, content] of [["Expected", finding.expected], ["Reported", finding.reported], ["Difference", finding.difference]]) {
      const card = el("div", null, "amount-card");
      card.append(el("span", label, "label"), el("span", content === null ? "—" : content, "amount")); amounts.append(card);
    }
    byId("financial-state").textContent = "Saved data state: " + finding.data_state + (finding.provisional ? " · provisional observation" : "") + " · no financial recomputation";
    byId("finding-json").textContent = pretty(finding);
    const issues = byId("finding-issues"); issues.replaceChildren();
    for (const issue of finding.issues || []) issues.append(el("div", issue.code + (issue.detail ? ": " + issue.detail : ""), "issue"));
    const entries = byId("evidence"); entries.replaceChildren();
    const reports = new Set(finding.report_ids || []);
    const ids = [...(finding.evidence_ids || [])].sort((a,b) => Number(reports.has(b)) - Number(reports.has(a)) || a.localeCompare(b));
    for (const id of ids) entries.append(renderEvidence(id));
    if (!ids.length) entries.append(el("p", "This saved finding lists no evidence. Its saved financial state remains visible.", "empty"));
    byId("receipt-section").hidden = true; byId("origin-section").hidden = true;
    for (const button of document.querySelectorAll(".finding-button")) button.setAttribute("aria-pressed", String(Number(button.dataset.ordinal) === ordinal));
  }

  function renderFindings() {
    const asset = byId("asset-filter").value, list = byId("findings"); list.replaceChildren();
    let count = 0;
    run.findings.forEach((finding, ordinal) => {
      if (asset && finding.asset !== asset) return;
      count++;
      const button = el("button", null, "finding-button"); button.type = "button";
      button.dataset.ordinal = String(ordinal); button.setAttribute("aria-pressed", String(selected === ordinal));
      button.append(el("strong", finding.asset + " / " + finding.comparison + " / " + finding.scope));
      const bottom = el("span", null, "finding-bottom");
      bottom.append(tag(finding.reconciliation_state, finding.reconciliation_state === "MISMATCH" ? "bad" : finding.reconciliation_state === "MATCHED" ? "good" : "warning"), el("span", "Δ " + value(finding.difference), "delta"));
      button.append(bottom); button.addEventListener("click", () => {chooseFinding(ordinal); byId("finding-detail").focus();}); list.append(button);
    });
    byId("finding-count").textContent = count + " / " + run.findings.length;
    if (!count) list.append(el("p", "No finding matches this asset filter.", "empty"));
  }
  for (const asset of [...new Set(run.findings.map(finding => finding.asset))].sort()) {
    const option = el("option", asset); option.value = asset; byId("asset-filter").append(option);
  }
  byId("asset-filter").addEventListener("change", renderFindings);
  const firstMismatch = run.findings.findIndex(finding => finding.reconciliation_state === "MISMATCH");
  if (run.findings.length) chooseFinding(firstMismatch >= 0 ? firstMismatch : 0);
  renderFindings();
})();
