"""Prepare the Assignment 3 golden, live-query, and human review datasets."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

EXTRA = [
    {"id": "q16", "type": "hard", "question": "How many regular semesters make up the minimum duration of a Bachelor's degree?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 10, "section": "1.23"}],
     "expect": "Eight regular semesters (four academic years).", "required_answer_patterns": ["eight regular semesters", "four academic years"]},
    {"id": "q17", "type": "hard", "question": "Which months bound the current undergraduate academic year?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 7, "section": "1.2"}],
     "expect": "It starts in August/September and ends in May/June.", "required_answer_patterns": ["august", "september", "may", "june"]},
    {"id": "q18", "type": "abstain", "question": "What is the 2026 hostel key deposit for FAST Islamabad?", "relevant": [], "must_abstain": True},
    {"id": "q19", "type": "abstain", "question": "What date will the university hold the next convocation?", "relevant": [], "must_abstain": True},
    {"id": "q20", "type": "abstain", "question": "Which bus route serves a student's home address in Rawalpindi?", "relevant": [], "must_abstain": True},
    {"id": "q21", "type": "hard", "question": "Under clause 1.21, what attendance is prescribed and what genuine-reason absence may the HoD condone?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 10, "section": "1.21"}],
     "expect": "100% attendance, with up to 20% absence condonable by the HoD for genuine reasons.", "required_answer_patterns": ["100\\s*%", "20\\s*%", "HoD", "genuine"]},
    {"id": "q22", "type": "hard", "question": "What happens to final-exam eligibility and the grade when a student fails the attendance requirement?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 10, "section": "1.22"}],
     "expect": "The student is ineligible for the final exam and receives F/A.", "required_answer_patterns": ["ineligible", "F/A"]},
    {"id": "q23", "type": "hard", "question": "How long is one classroom teaching period, and how many credit hours is a lab or workshop normally assigned?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 7, "section": "1.8"}, {"source": "academic-rules-handbook-jun-2026.pdf", "page": 8, "section": "1.10"}],
     "expect": "50 to 60 minutes; 1 or 2 credit hours.", "required_answer_patterns": ["50", "60", "1 or 2 credit hours"]},
    {"id": "q24", "type": "hard", "question": "Compare the optional summer-semester duration in the August 2023 rules with the current rules.",
     "relevant": [{"source": "undergraduate-academic-rules-aug-2023.pdf", "page": 20, "section": "6. Rules for Summer Semester"}, {"source": "academic-rules-handbook-jun-2026.pdf", "page": 28, "section": "6.1"}],
     "expect": "The 2023 rules say 8 to 9 weeks; the current rules say 8 weeks.", "required_answer_patterns": ["8 to 9 weeks", "8 weeks"]},
    {"id": "q25", "type": "hard", "question": "Can generative AI be the only source in preparatory research, and what restriction applies?",
     "relevant": [{"source": "student-handbook-jun-2026.pdf", "page": 50, "section": "4. Acceptable Uses of Generative AI Tools"}],
     "expect": "No. AI may support preparatory research but must not be the only source.", "required_answer_patterns": ["never be the only source"]},
]

NEW_COVERAGE = [
    {"id": "q26", "type": "ordinary", "question": "What does an A grade mean?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 11,
                   "section": "2.2"}], "expect": "Excellent",
     "required_answer_patterns": ["excellent"]},
    {"id": "q27", "type": "ordinary", "question": "How many years of publications are considered?",
     "relevant": [{"source": "faculty-entrepreneurship-and-technical-start-ups-policy.pdf",
                   "page": 2}],
     "expect": "One impact-factor journal paper from the two years before applying, at least online with a DOI and NUCES affiliation.",
     "required_answer_patterns": ["two years", "DOI", "NUCES"]},
    {"id": "q28", "type": "ordinary", "question": "What does the university annual report cover?",
     "relevant": [{"source": "annual-report-2019-20.pdf", "page": 27,
                   "section": "4. Formulate analytical reports extracted from the received feedback from the"}],
     "expect": "Analytical reports from stakeholder feedback (infrastructure, teaching, alumni and employers) with recommendations to university statutory bodies.",
     "required_answer_patterns": ["stakeholder", "recommendations"]},
    {"id": "q29", "type": "ordinary", "question": "Which section defines academic warning?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 19,
                   "section": "4.4"}],
     "expect": "Section 4.4 covers students under academic warning or probation.",
     "required_answer_patterns": ["4.4", "warning"]},
    {"id": "q30", "type": "ordinary", "question": "What does the current handbook say about CGPA?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 25,
                   "section": "5.9"}],
     "expect": "A student may repeat any course to improve CGPA.",
     "required_answer_patterns": ["repeat", "CGPA"]},
    {"id": "q31", "type": "ordinary", "question": "What is the grade interpretation for A minus?",
     "relevant": [{"source": "academic-rules-handbook-jun-2026.pdf", "page": 11,
                   "section": "2.2"}], "expect": "Excellent",
     "required_answer_patterns": ["excellent"]},
]

LIVE_IN = [
    "When does the current academic year begin?", "How long is a classroom teaching period?",
    "What CGPA avoids an academic warning?", "What does an A grade mean?",
    "How many credit hours does a lab usually carry?", "May students use generative AI for research?",
    "How much absence can the HoD condone?", "How long is the summer semester now?",
    "What does clause 1.22 say about attendance?", "How long is a bachelor's degree?",
    "What attendance rule applies to undergraduates?", "What did the 2023 rules say about summer?",
    "What is the faculty startup journal requirement?", "How many years of publications are considered?",
    "What does the university annual report cover?", "What is the prospectus academic rules summary?",
    "What are acceptable uses of generative AI tools?", "Which section defines academic warning?",
    "When does the academic year end?", "What consequence follows missed attendance?",
    "How many semesters are in a bachelor's degree?", "What does the current handbook say about CGPA?",
    "How long is a classroom period in minutes?", "What is the grade interpretation for A minus?",
    "What are the academic-year start and end months?", "What does the ORIC startup policy require?",
    "What is the student's attendance requirement?", "What is the university policy on AI?",
]
LIVE_OUT = [
    "What is today's weather in Islamabad?", "Who won yesterday's cricket match?",
    "What is the hostel visitor curfew?", "How much is the room-key deposit?",
    "What is the current semester tuition fee?", "When is the next convocation ceremony?",
    "Which bus route serves my home address?", "What is the cafeteria menu today?",
    "How do I renew my passport?", "What is the exchange rate this morning?",
    "Which hospital is nearest to campus?", "What are today's stock market prices?",
]

PARAPHRASE_PAIRS = [
    ("When does the current academic year start and finish?", "Which months begin and end the academic year?"),
    ("How many minutes does one classroom period last?", "What is the length of a teaching period in minutes?"),
    ("What CGPA is needed to stay off academic warning?", "Which undergraduate GPA threshold avoids a warning?"),
    ("What meaning is assigned to grades A and A minus?", "How are A and A- interpreted in the grade table?"),
    ("How many credits does a lab or workshop normally carry?", "What is the usual credit-hour load for lab courses?"),
    ("May AI tools be the sole source for preparatory research?", "Can a student rely only on generative AI when preparing research?"),
    ("What portion of absence may the HoD excuse for a genuine reason?", "How much course absence can the department head condone?"),
    ("How many weeks long is the current summer semester?", "What is the duration of today's undergraduate summer term?"),
    ("What penalty applies if attendance is below the rule?", "What follows when a student misses the attendance requirement?"),
    ("What is the minimum time to complete a bachelor's degree?", "How many years are required for a bachelor's program at minimum?"),
    ("What attendance is required in an undergraduate course?", "What percentage must undergraduates attend?"),
    ("How long was the optional summer term in the 2023 rules?", "What duration did the August 2023 rules give for summer semester?"),
    ("What journal evidence is needed for the faculty startup policy?", "Which publication must a faculty startup applicant show?"),
    ("What time range is considered for journal publication evidence?", "How far back must the qualifying publication be?"),
    ("Which policy describes acceptable generative AI uses?", "Where does the student handbook explain permitted AI use?"),
]
UNRELATED_PAIRS = [
    ("When does the current academic year start and finish?", "How do I renew a passport at the embassy?"),
    ("How many minutes does one classroom period last?", "What is the weather forecast for Islamabad tomorrow?"),
    ("What CGPA is needed to stay off academic warning?", "Which stock has the highest market capitalization?"),
    ("What meaning is assigned to grades A and A minus?", "How do I prepare chicken biryani at home?"),
    ("How many credits does a lab or workshop normally carry?", "What is the current exchange rate for euros?"),
    ("May AI tools be the sole source for preparatory research?", "Who won the latest international cricket final?"),
    ("What portion of absence may the HoD excuse for a genuine reason?", "How do I replace a damaged car tire?"),
    ("How many weeks long is the current summer semester?", "Which mountain is tallest in South America?"),
    ("What penalty applies if attendance is below the rule?", "How can I train a puppy to sit?"),
    ("What is the minimum time to complete a bachelor's degree?", "What causes thunderstorms in tropical regions?"),
    ("What attendance is required in an undergraduate course?", "How much water should a houseplant receive?"),
    ("How long was the optional summer term in the 2023 rules?", "What are the opening hours of the national museum?"),
    ("What journal evidence is needed for the faculty startup policy?", "How does a solar panel generate electricity?"),
    ("What time range is considered for journal publication evidence?", "Which recipe uses fresh basil and tomatoes?"),
    ("Which policy describes acceptable generative AI uses?", "Where can I buy a replacement phone battery?"),
]


def main() -> int:
    base = yaml.safe_load((ROOT / "golden.yaml").read_text(encoding="utf-8"))["questions"]
    for row in base:
        row["authoring_status"] = "inherited_from_assignment_2_verify_group_authorship"
        row["hard"] = row["id"] in {"q06", "q08", "q09", "q15"}
    for row in EXTRA:
        row["authoring_status"] = "ai_draft_group_review_required"
        row["review_status"] = "pending"
        row["hard"] = row["type"] == "hard"
    questions = base + EXTRA
    (ROOT / "golden.jsonl").write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions), encoding="utf-8")
    coverage = [dict(row) for row in questions]
    for row in NEW_COVERAGE:
        coverage.append({**row, "authoring_status": "ai_draft_group_review_required",
                         "review_status": "pending", "hard": False})
    (ROOT / "golden_after_coverage.jsonl").write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in coverage), encoding="utf-8")
    live = ([{"id": f"in-{i:02d}", "domain": "in", "question": q} for i, q in enumerate(LIVE_IN, 1)] +
            [{"id": f"out-{i:02d}", "domain": "out", "question": q} for i, q in enumerate(LIVE_OUT, 1)])
    (ROOT / "live_queries.jsonl").write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in live), encoding="utf-8")
    pairs = ([{"kind": "paraphrase", "left": left, "right": right} for left, right in PARAPHRASE_PAIRS] +
             [{"kind": "unrelated", "left": left, "right": right} for left, right in UNRELATED_PAIRS])
    (ROOT / "embedding_pairs.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs), encoding="utf-8")
    # Review prompts are intentionally not counted as human-authored or reviewed until
    # a teammate fills the attribution and review columns.
    review_path = ROOT / "assignment3/human_review.csv"
    previous: dict[str, dict[str, str]] = {}
    if review_path.exists():
        with review_path.open(encoding="utf-8", newline="") as stream:
            previous = {item["question_id"]: item for item in csv.DictReader(stream)}
    with review_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["question_id", "human_authored_by_group_member", "synthetic_question_reviewed_by_group_member", "reviewer", "notes"])
        for row in questions:
            old = previous.get(row["id"], {})
            writer.writerow([row["id"], old.get("human_authored_by_group_member", ""),
                             old.get("synthetic_question_reviewed_by_group_member", ""),
                             old.get("reviewer", ""), old.get("notes", "")])
    print(f"Prepared {len(questions)} golden questions ({sum(not q.get('must_abstain', False) for q in questions)} answerable, {sum(q.get('must_abstain', False) for q in questions)} abstain) and {len(live)} live queries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
