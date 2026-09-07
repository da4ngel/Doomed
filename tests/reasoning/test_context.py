from src.agents.analyst import Analysis, SeedEntity
from src.agents.context import focused_chunks


def test_visual_context_keeps_exact_subject_and_its_conflicting_sources(chunk):
    analysis = Analysis(
        normalized="Greyfell Citadel",
        requires_visual=True,
        seed_entities=[SeedEntity(entity_id="e", surface="Greyfell Citadel", type="Location")],
    )
    correct = chunk.model_copy(update={"doc_id": "images/plate_09_location_greyfell_citadel.png"})
    other = chunk.model_copy(
        update={
            "doc_id": "images/ironfell_citadel.png",
            "title": "Ironfell Citadel",
            "section_path": [],
            "text": "Unlike Greyfell Citadel",
        }
    )
    duplicate = correct.model_copy(update={"chunk_id": "second", "text": "A different number"})
    assert focused_chunks(analysis, [other, correct, duplicate]) == [correct, duplicate]
    assert focused_chunks(analysis, [other]) == [other]
    assert focused_chunks(Analysis(normalized="Question"), [other, correct]) == [other, correct]
