"""Typer CLI for Evidence Currency Monitor."""

import csv
import json
import random
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .ingest import ingest_topic, ingest_new_citers, check_integrity_all, get_stats, ingest_retracted

app = typer.Typer(help="Evidence Currency Monitor CLI")
console = Console()


# ---------------------------------------------------------------------------
# Phase 1 commands
# ---------------------------------------------------------------------------

@app.command("ingest-topic")
def cmd_ingest_topic(
    query: str = typer.Argument(..., help="Search query"),
    from_year: int = typer.Option(None, "--from-year", help="Earliest publication year"),
    to_year: int = typer.Option(None, "--to-year", help="Latest publication year"),
    max_papers: int = typer.Option(100, "--max-papers", help="Max papers to fetch"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass disk cache"),
):
    """Search OpenAlex and ingest matching papers."""
    console.print(f"[bold]Ingesting topic:[/bold] {query!r}")
    result = ingest_topic(query, from_year, to_year, max_papers, refresh=refresh)
    console.print(
        f"  papers_new={result['papers_new']}  "
        f"papers_updated={result['papers_updated']}  "
        f"citations_new={result['citations_new']}  "
        f"status={result['status']}"
    )


@app.command("ingest-citers")
def cmd_ingest_citers(
    since_date: str = typer.Option(None, "--since-date", help="ISO date, e.g. 2024-01-01"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass disk cache"),
):
    """Fetch works that cite papers already in the database."""
    console.print("[bold]Ingesting new citers…[/bold]")
    result = ingest_new_citers(since_date=since_date, refresh=refresh)
    console.print(
        f"  papers_new={result['papers_new']}  "
        f"papers_updated={result['papers_updated']}  "
        f"citations_new={result['citations_new']}"
    )


@app.command("ingest-retracted")
def cmd_ingest_retracted(
    query: str = typer.Argument(..., help="Search query to match retracted papers"),
    max_papers: int = typer.Option(5, "--max-papers", help="Max retracted papers to fetch"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass disk cache"),
):
    """Fetch retracted papers matching the query, their citers, and run integrity checks."""
    console.print(f"[bold]Ingesting retracted papers for:[/bold] {query!r}")
    result = ingest_retracted(query, max_papers=max_papers, refresh=refresh)
    console.print(
        f"  papers_new={result['papers_new']}  "
        f"papers_updated={result['papers_updated']}  "
        f"citations_new={result['citations_new']}  "
        f"notices_found={result['notices_found']}  "
        f"status={result['status']}"
    )


@app.command("check-integrity")
def cmd_check_integrity(
    refresh: bool = typer.Option(False, "--refresh", help="Bypass disk cache"),
):
    """Check all papers with DOIs against Crossref for retractions / corrections."""
    console.print("[bold]Checking integrity…[/bold]")
    result = check_integrity_all(refresh=refresh)
    console.print(f"  notices_found={result['notices_found']}")


@app.command("stats")
def cmd_stats():
    """Print row counts and the last 5 ingest runs."""
    data = get_stats()
    counts = data["counts"]

    t = Table(title="Table counts")
    t.add_column("Table")
    t.add_column("Rows", justify="right")
    for name, val in counts.items():
        t.add_row(name, str(val))
    console.print(t)

    runs_table = Table(title="Last 5 ingest runs")
    runs_table.add_column("ID")
    runs_table.add_column("Query")
    runs_table.add_column("Status")
    runs_table.add_column("Papers new", justify="right")
    runs_table.add_column("Started")
    for r in data["recent_runs"]:
        runs_table.add_row(r["id"], r["query"] or "", r["status"], str(r["papers_new"]), r["started_at"])
    console.print(runs_table)


# ---------------------------------------------------------------------------
# Phase 2 commands
# ---------------------------------------------------------------------------

@app.command("extract")
def cmd_extract(
    limit: int = typer.Option(None, "--limit", "-n", help="Max papers to process"),
    force: bool = typer.Option(False, "--force", help="Re-extract even if already done"),
    paper_id: str = typer.Option(None, "--paper-id", help="Extract only this paper"),
):
    """Extract empirical claims from paper abstracts using an LLM."""
    from .extraction.run import run_extraction

    console.print("[bold]Extracting claims…[/bold]")
    counts = run_extraction(limit=limit, force=force, paper_id=paper_id)
    console.print(
        f"  ok={counts.get('ok', 0)}  "
        f"empty={counts.get('empty', 0)}  "
        f"failed={counts.get('failed', 0)}  "
        f"skipped={counts.get('skipped', 0)}"
    )


@app.command("show-claims")
def cmd_show_claims(
    paper_id: str = typer.Argument(..., help="OpenAlex paper ID"),
):
    """Print claims and abstract for one paper."""
    from sqlalchemy import select
    from .db import session_scope
    from .models import Paper, Claim

    with session_scope() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            console.print(f"[red]Paper not found:[/red] {paper_id}")
            raise typer.Exit(1)
        claims = session.execute(
            select(Claim).where(Claim.paper_id == paper_id)
        ).scalars().all()

    console.print(Panel(paper.abstract or "(no abstract)", title=f"Abstract — {paper.title}", expand=False))

    if not claims:
        console.print("[yellow]No claims extracted yet. Run `extract --paper-id ID` first.[/yellow]")
        return

    for i, c in enumerate(claims, 1):
        t = Table(title=f"Claim {i}", show_header=False, expand=False)
        t.add_column("Field", style="bold", width=22)
        t.add_column("Value")
        t.add_row("claim_text", c.claim_text)
        t.add_row("source_sentence", c.source_sentence)
        t.add_row("direction", c.direction or "—")
        t.add_row("effect_reported", c.effect_reported or "—")
        t.add_row("population", c.population or "—")
        t.add_row("country_or_setting", c.country_or_setting or "—")
        t.add_row("design", c.design or "—")
        t.add_row("outcome_measure", c.outcome_measure or "—")
        t.add_row("sample_size", str(c.sample_size) if c.sample_size else "—")
        t.add_row("follow_up", c.follow_up or "—")
        t.add_row("is_primary_claim", str(c.is_primary_claim))
        t.add_row("confidence", f"{c.extraction_confidence} — {c.confidence_note or ''}")
        t.add_row("fields_missing", ", ".join(json.loads(c.fields_missing_json or "[]")) or "none")
        console.print(t)


@app.command("export-review")
def cmd_export_review(
    n: int = typer.Option(20, "--n", help="Number of claims to sample"),
    out: Path = typer.Option(Path("review.csv"), "--out", help="Output CSV path"),
):
    """Export a random sample of claims for manual quality review."""
    from sqlalchemy import select
    from .db import session_scope
    from .models import Paper, Claim

    with session_scope() as session:
        rows = session.execute(
            select(Claim, Paper).join(Paper, Claim.paper_id == Paper.id)
        ).all()

    if not rows:
        console.print("[yellow]No claims in DB. Run `extract` first.[/yellow]")
        raise typer.Exit(1)

    sample = random.sample(rows, min(n, len(rows)))

    fieldnames = [
        "paper_id", "paper_title", "abstract",
        "source_sentence", "claim_text",
        "population", "design", "sample_size", "effect_reported",
        "correct_claim (y/n)", "source_exact (y/n)", "any_invented_detail (y/n)", "notes",
    ]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for claim, paper in sample:
            writer.writerow({
                "paper_id": paper.id,
                "paper_title": paper.title or "",
                "abstract": paper.abstract or "",
                "source_sentence": claim.source_sentence,
                "claim_text": claim.claim_text,
                "population": claim.population or "",
                "design": claim.design or "",
                "sample_size": claim.sample_size or "",
                "effect_reported": claim.effect_reported or "",
                "correct_claim (y/n)": "",
                "source_exact (y/n)": "",
                "any_invented_detail (y/n)": "",
                "notes": "",
            })

    console.print(f"[green]Wrote {len(sample)} claims to {out}[/green]")


@app.command("review-score")
def cmd_review_score(
    csv_path: Path = typer.Argument(..., help="Filled review CSV"),
):
    """Read a filled review CSV and report quality percentages."""
    if not csv_path.exists():
        console.print(f"[red]File not found:[/red] {csv_path}")
        raise typer.Exit(1)

    total = correct = exact_source = no_invented = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cc = row.get("correct_claim (y/n)", "").strip().lower()
            se = row.get("source_exact (y/n)", "").strip().lower()
            ai = row.get("any_invented_detail (y/n)", "").strip().lower()
            if not cc:
                continue  # skip unfilled rows
            total += 1
            if cc == "y":
                correct += 1
            if se == "y":
                exact_source += 1
            if ai == "n":
                no_invented += 1

    if total == 0:
        console.print("[yellow]No filled rows found. Fill in y/n columns first.[/yellow]")
        return

    t = Table(title=f"Review scores ({total} claims rated)")
    t.add_column("Metric")
    t.add_column("Score", justify="right")
    t.add_row("Claims correct", f"{correct}/{total} ({100*correct//total}%)")
    t.add_row("Source sentences exact", f"{exact_source}/{total} ({100*exact_source//total}%)")
    t.add_row("No invented details", f"{no_invented}/{total} ({100*no_invented//total}%)")
    console.print(t)


# ---------------------------------------------------------------------------
# Phase 3 commands
# ---------------------------------------------------------------------------

@app.command("find-candidates")
def cmd_find_candidates(
    limit: int = typer.Option(None, "--limit", "-n", help="Max anchor claims to process"),
    force: bool = typer.Option(False, "--force", help="Rebuild embeddings"),
):
    """Embed claims and find candidate pairs."""
    from .comparison.candidates import build_embeddings, find_candidates
    console.print("[bold]Building embeddings…[/bold]")
    n = build_embeddings(force=force)
    console.print(f"  embeddings created/updated: {n}")
    console.print("[bold]Finding candidate pairs…[/bold]")
    pairs = find_candidates(limit=limit)
    console.print(f"  new claim pairs: {pairs}")


@app.command("build-cases")
def cmd_build_cases(
    limit: int = typer.Option(None, "--limit", "-n", help="Max anchor claims for candidate step"),
    force: bool = typer.Option(False, "--force", help="Reprocess already-done steps"),
):
    """Run the full comparison pipeline: relevance → compare → classify → skeptic → rank."""
    from .comparison.pipeline import run_pipeline
    console.print("[bold]Running comparison pipeline…[/bold]")
    summary = run_pipeline(limit=limit, force=force)
    for k, v in summary.items():
        console.print(f"  {k}: {v}")


@app.command("show-case")
def cmd_show_case(
    case_id: str = typer.Argument(..., help="Case ID"),
):
    """Print full details of one Case."""
    from sqlalchemy import select
    from .db import session_scope
    from .models import Case, Claim, Paper, FieldComparison, ClaimPair, AffectedItem

    with session_scope() as session:
        case = session.get(Case, case_id)
        if not case:
            # Try prefix match
            from sqlalchemy import select as _select
            case = session.execute(
                _select(Case).where(Case.id.like(f"{case_id}%"))
            ).scalars().first()
        if not case:
            console.print(f"[red]Case not found:[/red] {case_id}")
            raise typer.Exit(1)
        anchor = session.get(Claim, case.anchor_claim_id)
        new = session.get(Claim, case.new_claim_id) if case.new_claim_id else None
        anchor_paper = session.get(Paper, anchor.paper_id) if anchor else None
        new_paper = session.get(Paper, new.paper_id) if new else None

        pair = session.execute(
            select(ClaimPair).where(
                ClaimPair.anchor_claim_id == case.anchor_claim_id,
                ClaimPair.new_claim_id == case.new_claim_id,
            )
        ).scalar_one_or_none() if case.new_claim_id else None

        comparisons = session.execute(
            select(FieldComparison).where(FieldComparison.claim_pair_id == pair.id)
        ).scalars().all() if pair else []

        affected = session.execute(
            select(AffectedItem).where(AffectedItem.case_id == case_id)
            .order_by(AffectedItem.score.desc())
        ).scalars().all()

    console.rule(f"Case {case_id[:8]}")
    console.print(f"[bold]Label:[/bold] [yellow]{case.label}[/yellow]  "
                  f"[bold]Confidence:[/bold] {case.confidence}  "
                  f"[bold]Priority:[/bold] {case.priority_score}")
    console.print(f"[bold]Rationale:[/bold] {case.rationale}")
    if case.needs_human_attention:
        console.print("[red bold]⚠ Needs human attention[/red bold]")

    console.rule("Anchor claim")
    console.print(Panel(anchor.source_sentence, title=anchor_paper.title[:60] if anchor_paper else ""))
    console.print(f"  {anchor.claim_text}")

    if new:
        console.rule("New claim")
        console.print(Panel(new.source_sentence, title=new_paper.title[:60] if new_paper else ""))
        console.print(f"  {new.claim_text}")

    if comparisons:
        console.rule("Field comparisons")
        t = Table(show_header=True)
        t.add_column("Field")
        t.add_column("Anchor")
        t.add_column("New")
        t.add_column("Result")
        for fc in comparisons:
            color = {"similar": "green", "differs": "red", "unknown": "dim"}.get(fc.result, "")
            t.add_row(fc.field_name, fc.anchor_value or "—", fc.new_value or "—",
                      f"[{color}]{fc.result}[/{color}]" if color else fc.result)
        console.print(t)

    if case.skeptic_verdict:
        console.rule("Skeptic")
        console.print(f"  Verdict: [bold]{case.skeptic_verdict}[/bold]  "
                      f"Alt label: {case.alternative_label}")
        console.print(f"  {case.skeptic_argument}")

    if affected:
        console.rule("Affected papers (ranked)")
        t2 = Table(show_header=True)
        t2.add_column("Score", justify="right")
        t2.add_column("Relation")
        t2.add_column("Paper ID")
        for item in affected:
            t2.add_row(str(item.score), item.relation or "", item.paper_id[-20:])
        console.print(t2)


@app.command("list-cases")
def cmd_list_cases(
    label: str = typer.Option(None, "--label", help="Filter by label"),
    attention: bool = typer.Option(False, "--attention", help="Only cases needing human attention"),
    limit: int = typer.Option(50, "--limit"),
):
    """List cases, optionally filtered."""
    from sqlalchemy import select
    from .db import session_scope
    from .models import Case

    with session_scope() as session:
        q = select(Case).order_by(Case.priority_score.desc()).limit(limit)
        if label:
            q = q.where(Case.label == label)
        else:
            q = q.where(Case.label != "unrelated")
        if attention:
            q = q.where(Case.needs_human_attention == True)
        cases = session.execute(q).scalars().all()

    t = Table(title=f"Cases ({len(cases)})")
    t.add_column("ID")
    t.add_column("Label")
    t.add_column("Conf")
    t.add_column("Priority", justify="right")
    t.add_column("Attention")
    t.add_column("Skeptic")
    for c in cases:
        t.add_row(
            c.id[:8], c.label, c.confidence or "—",
            str(c.priority_score or "—"),
            "⚠" if c.needs_human_attention else "",
            c.skeptic_verdict or "—",
        )
    console.print(t)


@app.command("export-case-review")
def cmd_export_case_review(
    n: int = typer.Option(20, "--n"),
    out: Path = typer.Option(Path("cases.csv"), "--out"),
):
    """Export a random sample of Cases for manual review."""
    from sqlalchemy import select
    from .db import session_scope
    from .models import Case, Claim, Paper

    with session_scope() as session:
        cases = session.execute(select(Case).where(Case.label != "unrelated")).scalars().all()
        rows = []
        for case in cases:
            anchor = session.get(Claim, case.anchor_claim_id)
            new = session.get(Claim, case.new_claim_id) if case.new_claim_id else None
            anchor_paper = session.get(Paper, anchor.paper_id) if anchor else None
            rows.append((case, anchor, new, anchor_paper))

    # Stratified sample: take all rare labels first, fill rest from common labels
    from collections import defaultdict
    by_label: dict = defaultdict(list)
    for row in rows:
        by_label[row[0].label].append(row)

    rare_labels = {lbl for lbl, lrows in by_label.items() if len(lrows) <= 5}
    sample = []
    for lbl in rare_labels:
        sample.extend(by_label[lbl])

    common_rows = [r for r in rows if r[0].label not in rare_labels]
    remaining = n - len(sample)
    if remaining > 0 and common_rows:
        sample.extend(random.sample(common_rows, min(remaining, len(common_rows))))
    sample = sample[:n]
    fieldnames = [
        "case_id", "label", "confidence", "anchor_claim", "anchor_source",
        "new_claim", "new_source", "rationale", "skeptic_verdict", "needs_attention",
        "label_correct (y/n)", "evidence_fair (y/n)", "skeptic_useful (y/n)", "notes",
    ]
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for case, anchor, new, anchor_paper in sample:
            writer.writerow({
                "case_id": case.id,
                "label": case.label,
                "confidence": case.confidence or "",
                "anchor_claim": anchor.claim_text if anchor else "",
                "anchor_source": anchor.source_sentence if anchor else "",
                "new_claim": new.claim_text if new else "",
                "new_source": new.source_sentence if new else "",
                "rationale": case.rationale or "",
                "skeptic_verdict": case.skeptic_verdict or "",
                "needs_attention": "yes" if case.needs_human_attention else "no",
                "label_correct (y/n)": "",
                "evidence_fair (y/n)": "",
                "skeptic_useful (y/n)": "",
                "notes": "",
            })
    console.print(f"[green]Wrote {len(sample)} cases to {out}[/green]")


@app.command("case-score")
def cmd_case_score(
    csv_path: Path = typer.Argument(...),
):
    """Read a filled case review CSV and print quality percentages."""
    if not csv_path.exists():
        console.print(f"[red]File not found:[/red] {csv_path}")
        raise typer.Exit(1)

    total = label_ok = evidence_ok = skeptic_ok = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lc = row.get("label_correct (y/n)", "").strip().lower()
            ef = row.get("evidence_fair (y/n)", "").strip().lower()
            su = row.get("skeptic_useful (y/n)", "").strip().lower()
            if not lc:
                continue
            total += 1
            if lc == "y": label_ok += 1
            if ef == "y": evidence_ok += 1
            if su == "y": skeptic_ok += 1

    if total == 0:
        console.print("[yellow]No filled rows found.[/yellow]")
        return

    t = Table(title=f"Case review scores ({total} rated)")
    t.add_column("Metric")
    t.add_column("Score", justify="right")
    t.add_row("Label correct", f"{label_ok}/{total} ({100*label_ok//total}%)")
    t.add_row("Evidence fair", f"{evidence_ok}/{total} ({100*evidence_ok//total}%)")
    t.add_row("Skeptic useful", f"{skeptic_ok}/{total} ({100*skeptic_ok//total}%)")
    console.print(t)


if __name__ == "__main__":
    app()
