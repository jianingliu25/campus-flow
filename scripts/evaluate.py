"""Reproducible offline evaluation, with authored provenance and no live-model claims."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.agent.data import Snapshot
from app.agent.orchestrator import Agent, execute_tool
from app.agent.router import route
from app.demo import load_fixtures
from app.ingest.extraction import rule_extract, validate_candidates


async def evaluate():
    path = ROOT / "eval/holdout/intent.json"
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != manifest["sha256"]:
        raise ValueError("Frozen evaluation hash changed")
    cases = json.loads(path.read_text(encoding="utf-8")); labels = sorted({item["intent"] for item in cases})
    predictions = [{**item, "predicted": route(item["query"]).intents[0]} for item in cases]
    metrics = {}
    for label in labels:
        tp = sum(row["intent"] == label == row["predicted"] for row in predictions)
        fp = sum(row["intent"] != label == row["predicted"] for row in predictions)
        fn = sum(row["intent"] == label != row["predicted"] for row in predictions)
        p, r = tp / (tp + fp) if tp + fp else 0, tp / (tp + fn) if tp + fn else 0
        metrics[label] = {"precision": p, "recall": r, "f1": 2*p*r/(p+r) if p+r else 0}
    bundle = load_fixtures(); corpus = Snapshot.fixtures(bundle)
    runs = [await Agent(corpus).run(case["query"]) for case in cases]
    ids = {mail["id"] for mail in corpus.emails}
    citation_total = sum(len(run["citations"]) for run in runs)
    # Referential validity is deliberately separate from answer correctness.
    valid = sum(citation["email_id"] in ids for run in runs for citation in run["citations"])
    correct_category = 0; expected_fields = 0; predicted_fields = 0; matched = 0
    fields = ["title", "type", "start_at", "end_at", "date", "location"]
    mapping = {"start_at": "start_at_utc", "end_at": "end_at_utc", "date": "event_date"}
    def normalize(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value
    for mail in bundle.emails:
        output = rule_extract(mail.subject, mail.body_text, mail.received_at, bundle.timezone)
        correct_category += output.category == mail.category
        accepted, _ = validate_candidates(output, mail.body_text, mail.received_at, bundle.timezone)
        gold = [event.model_dump() for event in bundle.events if event.source_email_id == mail.id]
        for row in gold:
            expected_fields += sum(row.get(key) is not None for key in fields)
        for row in accepted:
            predicted_fields += sum((row.get("event_date") or row.get("deadline_date") if key=="date" else row.get(mapping.get(key,key))) is not None for key in fields)
        # Exact fields within stable per-email event order; no fuzzy title credit.
        for expected, actual in zip(gold, accepted):
            for key in fields:
                value = expected.get(key); other = actual.get(mapping.get(key,key))
                if key == "date":
                    other = actual.get("event_date") or actual.get("deadline_date")
                if value is not None and normalize(value) == normalize(other):
                    matched += 1
    p = matched/predicted_fields if predicted_fields else 0; r = matched/expected_fields if expected_fields else 0
    ablation = []
    for repair in [0, 2]:
        calls = [0]
        def corrupt(task, data, results):
            result = deepcopy(execute_tool(task,data,results))
            if task.tool == "get_events":
                calls[0] += 1
                if calls[0] == 1 and result["data"]:
                    result["data"][0]["start_at"] += timedelta(days=1)
            return result
        result = await Agent(corpus,executor=corrupt,max_replans=repair).run("机器学习课与相关邮件是什么？")
        ablation.append({"max_replans":repair,"verification":result["verification_status"],"tool_calls":result["tool_calls"]})
    return {"reference_now": bundle.reference_now.isoformat(), "mode":"offline-rules-and-lexical",
            "holdout_provenance":manifest,"intent":{"accuracy":sum(row['intent']==row['predicted'] for row in predictions)/len(cases),
            "macro_f1":sum(item['f1'] for item in metrics.values())/len(metrics),"per_label":metrics,"predictions":predictions},
            "development_extraction":{"emails":len(bundle.emails),"classification_accuracy":correct_category/len(bundle.emails),
            "exact_field_precision":p,"exact_field_recall":r,"exact_field_f1":2*p*r/(p+r) if p+r else 0,
            "matched_fields":matched,"predicted_fields":predicted_fields,"gold_fields":expected_fields,
            "limitation":"Development corpus, per-email ordered matching; timezone representations are exact, not normalized semantic equivalence."},
            "citation_reference_validity":{"valid":valid,"total":citation_total,"answer_accuracy_measured":False},
            "repair_fault_injection":ablation,
            "not_validated":["real mailbox","vendor MCP schema adapters","learned model quality","semantic recommendation precision@5",
                             "FAISS runtime","external benchmark generalization","human graded answer correctness"]}


if __name__ == "__main__":
    result = asyncio.run(evaluate())
    output = ROOT / "eval/reports/offline.json"; output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"intent_accuracy":result["intent"]["accuracy"],"intent_macro_f1":result["intent"]["macro_f1"],
                      "development_extraction":result["development_extraction"],"repair":result["repair_fault_injection"]},ensure_ascii=True))
