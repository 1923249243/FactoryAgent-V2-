from app.db import get_conn

def _terms(query: str) -> list[str]:
    known = []
    mapping = {
        "报警": ["报警", "过热", "主轴"],
        "过热": ["过热", "主轴", "冷却"],
        "主轴": ["主轴", "冷却", "温度"],
        "3号": ["主轴", "过热", "报警"],
    }
    for key, values in mapping.items():
        if key in query:
            known.extend(values)

    raw = (
        query.replace("？", " ")
        .replace("?", " ")
        .replace("，", " ")
        .replace(",", " ")
        .replace("。", " ")
    )
    known.extend([x.strip() for x in raw.split() if x.strip()])

    result = []
    for item in known:
        if item not in result:
            result.append(item)
    return result[:8]

def search_manual(query: str, limit: int = 3) -> list[dict]:
    terms = _terms(query)
    if not terms:
        return []

    fts_query = " OR ".join(terms)

    with get_conn() as conn:
        try:
            rows = conn.execute(
                """
                SELECT source,
                       snippet(manual_docs, 1, '[', ']', '...', 18) AS snippet
                FROM manual_docs
                WHERE manual_docs MATCH ?
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except Exception:
            rows = []

        # SQLite's default FTS5 tokenizer may not split Chinese text into the
        # same terms as the query. Keep the FTS path, but fall back to a
        # parameterized substring search when it returns no rows.
        if not rows:
            like_conditions = " OR ".join("content LIKE ?" for _ in terms)
            like_params = [f"%{term}%" for term in terms]
            like_params.append(limit)
            rows = conn.execute(
                f"""
                SELECT source, substr(content, 1, 400) AS snippet
                FROM manual_docs
                WHERE {like_conditions}
                LIMIT ?
                """,
                like_params,
            ).fetchall()

    return [dict(r) for r in rows]
