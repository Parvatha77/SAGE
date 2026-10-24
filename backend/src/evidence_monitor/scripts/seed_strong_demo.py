"""
Seed database with strong, impressive demo cases across 3 focused areas.
Areas: Education Technology, Mental Health Interventions, Evidence-Based Policy
"""

import datetime
from evidence_monitor.db import session_scope
from evidence_monitor.models import Paper, Claim, Case, ClaimPair, Need, Brief


AREAS = {
    "Education": {
        "papers": [
            ("10.1038/s41598-2023-12345", 2023, "Asynchronous online learning increases retention by 34% in STEM",
             "Large RCT (n=2,847) found flipped classroom model with peer review increased end-of-term retention from 82% to 93%"),
            ("10.1109/tlt.2022-08765", 2022, "Real-time collaborative coding platforms improve debugging skills",
             "Students using paired programming tools showed 47% faster debugging compared to solo work (n=312, p<0.001)"),
            ("10.1016/j.compedu.2023-04321", 2023, "Spaced repetition algorithms boost long-term learning outcomes",
             "Adaptive spacing increased 6-month retention by 28 percentage points (controlled trial, n=1,203)"),
            ("10.1145/3478431", 2021, "AI tutoring reduces achievement gap in rural schools",
             "Personalized AI tutors decreased math achievement gap between high/low-income students by 22% in 8 weeks"),
            ("10.1080/10494820.2022.2156432", 2022, "Video summarization tools reduce cognitive load",
             "Auto-generated video summaries cut study time 31% while maintaining 89% comprehension (n=456)"),
        ],
        "case_pairs": [
            (0, 1, "affirms_claim", "high", "Both show effectiveness of interactive online learning. Collaborative coding validates peer-based engagement benefits."),
            (1, 2, "affirms_claim", "high", "Spaced repetition and coding practice both drive retention. Mechanisms are complementary - spacing + active learning."),
            (0, 3, "affirms_claim", "high", "Flipped classrooms and AI tutoring both show >20% improvement. AI scales personalization to all students regardless of SES."),
            (2, 3, "differs_in_context", "medium", "Both boost learning but for different populations: spaced repetition works universally, AI tutoring specifically targets disadvantaged students."),
            (1, 4, "affirms_claim", "high", "Collaborative tools and video summaries both reduce cognitive load through different mechanisms. Both can coexist in same platform."),
            (3, 4, "differs_in_context", "medium", "AI tutoring addresses equity gap while video tools address universal comprehension. Both needed for inclusive learning."),
            (0, 4, "affirms_claim", "medium", "Online learning + summarization could amplify each other. Flipped classroom + auto-summaries = faster content review."),
            (2, 4, "affirms_claim", "high", "Spaced repetition through algorithm + video summaries create synergy: summaries speed review, spacing optimizes retention."),
            (1, 3, "differs_in_context", "medium", "Collaborative coding improves skills in high-achieving students, while AI tutoring levels baseline for struggling learners. Complementary strategies."),
            (0, 2, "affirms_claim", "high", "Flipped classroom + spaced repetition both maximize active recall. Natural fit for same course design."),
        ],
    },
    "MentalHealth": {
        "papers": [
            ("10.1176/appi.ajp.2023.22090876", 2023, "CBT-delivered via app reduces anxiety by 41% in 12 weeks",
             "RCT (n=1,840) comparing app-based CBT to waitlist: clinician-supervised digital CBT showed 41% reduction in GAD-7 scores, sustained at 6-month follow-up"),
            ("10.1001/jamapsychiatry.2022.3842", 2022, "Mindfulness meditation + antidepressants outperforms either alone",
             "Combination therapy (n=923) showed 67% remission rate vs 52% meds-only, 41% meditation-only (p<0.001)"),
            ("10.1192/bjp.2023.45621", 2023, "Peer support groups cut readmission rates by 38%",
             "12-month follow-up (n=604): structured peer groups reduced psychiatric readmission from 54% to 33% (95% CI: 12-31%)"),
            ("10.1038/s41591-2023-01234", 2023, "Early intervention in psychosis shows 56% better outcomes",
             "First-episode psychosis (n=287): early detection + integrated care team resulted in 56% full remission vs 28% standard care"),
            ("10.1016/s0140-6736(23)00456-7", 2023, "Digital mental health outreach reaches 3x more underserved populations",
             "Telehealth program (n=4,203): 78% uptake in rural areas vs 23% in-person; same clinical outcomes as office-based care"),
        ],
        "case_pairs": [
            (0, 1, "affirms_claim", "high", "Both CBT and mindfulness show >40% symptom improvement. Combined approach achieves 67% remission - synergistic effect."),
            (1, 2, "affirms_claim", "high", "Medication + mindfulness + peer support create multi-level intervention. Peer groups complement psychotherapy, reduce relapse."),
            (0, 3, "differs_in_context", "medium", "App-based CBT works for anxiety, but early psychosis needs clinical team + medication. Different disorders, different intensity needs."),
            (2, 3, "affirms_claim", "high", "Both peer support and integrated care reduce readmission. Structural social support critical across multiple diagnoses."),
            (3, 4, "affirms_claim", "high", "Early intervention + digital reach create scalability. First-episode psychosis needs both rapid identification and accessible treatment."),
            (0, 4, "affirms_claim", "high", "App-based CBT + telehealth expand access to evidence-based care. Digital delivery maintains efficacy while reaching underserved groups."),
            (1, 4, "affirms_claim", "medium", "Mindfulness + digital delivery both feasible for remote delivery. Telehealth works for mild-moderate, but psychosis needs clinical assessment."),
            (2, 4, "affirms_claim", "high", "Peer support and digital outreach both expand service reach. Rural populations benefit from both telepsychiatry and peer groups."),
            (0, 2, "affirms_claim", "high", "CBT and peer support are compatible. Digital CBT + peer groups could be combined in single platform for better outcomes."),
            (3, 1, "differs_in_context", "high", "Psychosis remission (56%) higher than anxiety remission (41%), but psychosis is more severe baseline. Context matters for interpreting effect size."),
        ],
    },
    "Science": {
        "papers": [
            ("10.1257/aer.20190571", 2023, "UBI pilot increased employment by 8%, not reduced as opponents claimed",
             "Finland UBI trial (n=2,000): unconditional cash transfers increased job-seeking behavior 8%, contradicting reduction hypothesis"),
            ("10.1016/S0140-6736(23)00123-4", 2023, "Lead pipe replacement prevents 47% of childhood developmental delays",
             "Flint water crisis response (n=3,400): replacing lead pipes in first 2 years of life prevented 47% of IQ declines vs ongoing exposure"),
            ("10.1038/s41558-2023-01678-w", 2023, "Carbon pricing increases renewable adoption without net job loss",
             "EU carbon market (2005-2023): emissions fell 35% while green sector added 2.1M jobs, no net manufacturing job loss"),
            ("10.1093/jrsssb/2023.abcd123", 2023, "Randomized drug court reduces incarceration by 61%",
             "Multi-site RCT (n=1,889): treatment-focused courts 61% fewer incarcerations, 38% better employment outcomes than standard prosecution"),
            ("10.1186/s12939-2023-01890-2", 2023, "Free contraception reduces teen pregnancy 87% in implementation sites",
             "Colorado LARC program (2009-2019, n=50K): free long-acting contraception reduced teen birth rate 87% in participating regions"),
        ],
        "case_pairs": [
            (0, 1, "affirms_claim", "high", "Both UBI and lead remediation show policy can protect populations without unintended harms. Evidence challenges common opposition narratives."),
            (1, 2, "affirms_claim", "high", "Lead remediation + carbon pricing both show environmental policy improves health/economy. Prevention and climate action aligned."),
            (2, 3, "affirms_claim", "high", "Carbon pricing and drug courts both achieve policy goals via behavioral incentives, not restrictions. Market + treatment-based approaches work."),
            (3, 4, "affirms_claim", "high", "Drug courts and free contraception both use upstream prevention to reduce downstream costs. Prevention ROI >4:1 in both cases."),
            (0, 4, "affirms_claim", "high", "UBI and free contraception both remove economic barriers to positive outcomes. Unconditional support + universal access = behavior change."),
            (1, 3, "differs_in_context", "medium", "Lead remediation is universal (all children benefit), drug courts are targeted (criminal justice population). Different implementation scales."),
            (0, 2, "differs_in_context", "medium", "UBI affects labor economics, carbon pricing affects environmental behavior. Different mechanisms but both show unintended benefit."),
            (1, 4, "affirms_claim", "high", "Lead removal and contraception access both have 35-87% effect sizes. Preventing childhood harm (exposure vs pregnancy) both high ROI."),
            (2, 4, "affirms_claim", "medium", "Carbon pricing and contraception access both address equity gaps. Environmental justice + reproductive justice both work via access expansion."),
            (3, 0, "affirms_claim", "high", "Drug courts and UBI both challenge assumption that punitive/restrictive policies work. Treatment + support outperform control in both cases."),
        ],
    },
}


def seed_strong_demo():
    """Insert strong demo cases into database."""
    from evidence_monitor.db import create_all
    create_all()

    with session_scope() as s:
        # Clear existing demo data
        s.query(Case).filter(Case.id.like("DEMO-%")).delete()
        s.query(ClaimPair).filter(ClaimPair.id.like("DEMO-%")).delete()
        s.query(Claim).filter(Claim.paper_id.like("DEMO-%")).delete()
        s.query(Paper).filter(Paper.id.like("DEMO-%")).delete()

        case_idx = 0
        paper_map = {}
        claim_map = {}

        for area_name, area_data in AREAS.items():
            print(f"\n=== {area_name} ===")

            # Insert papers and claims
            for paper_idx, (doi, year, title, abstract) in enumerate(area_data["papers"]):
                paper_id = f"DEMO-{area_name.replace(' ', '-')}-{paper_idx}"
                paper = Paper(
                    id=paper_id,
                    title=title,
                    abstract=abstract,
                    publication_year=year,
                    doi=doi,
                )
                s.add(paper)
                paper_map[paper_idx] = paper_id

                claim = Claim(
                    id=f"{paper_id}-claim-0",
                    paper_id=paper_id,
                    claim_text=abstract,
                    source_sentence=abstract[:100],
                )
                s.add(claim)
                claim_map[paper_idx] = f"{paper_id}-claim-0"

            s.flush()

            # Insert case pairs
            for anchor_idx, new_idx, label, confidence, rationale in area_data["case_pairs"]:
                anchor_id = claim_map[anchor_idx]
                new_id = claim_map[new_idx]

                pair = ClaimPair(
                    id=f"DEMO-pair-{area_name.replace(' ', '-')}-{len(s.query(ClaimPair).all())}",
                    anchor_claim_id=anchor_id,
                    new_claim_id=new_id,
                    similarity=0.75,
                )
                s.add(pair)
                s.flush()

                case = Case(
                    id=f"DEMO-case-{case_idx}",
                    anchor_claim_id=anchor_id,
                    new_claim_id=new_id,
                    label=label,
                    confidence=confidence,
                    rationale=rationale,
                    status="open",
                    state="open",
                    priority_score=85 if confidence == "high" else 65,
                    created_at=datetime.datetime.now(),
                )
                s.add(case)
                case_idx += 1

            print(f"  → {len(area_data['papers'])} papers")
            print(f"  → {len(area_data['case_pairs'])} cases")

        # Create demo needs + briefs for UC2
        import json as _json
        needs_data = [
            ("Online Education for Underserved Populations",
             "How can online education reach underserved populations?",
             "Education Technology"),
            ("Scalable Mental Health Interventions",
             "What mental health interventions are evidence-proven and scalable?",
             "Mental Health Interventions"),
            ("Evidence-Based Policy Implementation",
             "How do we implement evidence-based policy without unintended harms?",
             "Evidence-Based Policy"),
        ]

        for idx, (title, need_question, area) in enumerate(needs_data):
            need = Need(
                id=f"DEMO-need-{idx}",
                title=title,
                source_name="SAGE Demo",
                need_text=need_question,
                audience="Policy makers and implementation partners",
                jurisdiction="National/Federal",
                topic_keywords_json=_json.dumps([area.lower().replace(" ", "-")]),
                population_of_interest="All populations",
                setting_of_interest="Broad implementation contexts",
                is_example=True,
                state="new",
                created_at=datetime.datetime.now(),
            )
            s.add(need)

        s.commit()
        print(f"\n✅ Seeded {case_idx} strong demo cases across 3 areas")


if __name__ == "__main__":
    seed_strong_demo()
