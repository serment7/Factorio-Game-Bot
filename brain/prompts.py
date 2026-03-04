"""Message builders for Brain → Claude CLI communication.

No separate system prompt is used. All context is embedded directly
in the user prompt to avoid Claude flagging role-assignment instructions
as prompt injection.
"""


def build_goal_request(
    current_goal: str,
    stats: dict[str, int],
    recent_observations: list[dict],
    known_controls: list[dict],
    known_entities: list[dict],
) -> str:
    obs_summary = ""
    if recent_observations:
        obs_lines = []
        for o in recent_observations[:10]:
            obs_lines.append(f"  - [{o['action_type']} {o['action_args']}] {o['thought'][:80]}")
        obs_summary = "\n".join(obs_lines)
    else:
        obs_summary = "  아직 관찰 없음."

    ctrl_summary = ""
    if known_controls:
        ctrl_lines = [f"  - {c['key']}: {c['effect']} (conf: {c['confidence']:.1f})"
                      for c in known_controls[:10]]
        ctrl_summary = "\n".join(ctrl_lines)
    else:
        ctrl_summary = "  아직 발견 없음."

    entity_summary = ""
    if known_entities:
        ent_lines = [f"  - {e['name']} ({e['category']}): seen {e['times_seen']}x"
                     for e in known_entities[:10]]
        entity_summary = "\n".join(ent_lines)
    else:
        entity_summary = "  아직 발견 없음."

    return f"""나는 팩토리오 게임을 자동 플레이하는 AI 에이전트를 만들고 있어.
아래는 에이전트의 현재 상태야. 이걸 보고 에이전트가 다음에 해야 할 게임 내 목표를 한글 1~2문장으로 알려줘.

현재 목표: {current_goal}

학습 통계:
- 발견한 조작법: {stats.get('known_controls', 0)}개
- 관찰 횟수: {stats.get('observations', 0)}회
- 위키 항목: {stats.get('wiki_entries', 0)}개
- 발견한 엔티티: {stats.get('known_entities', 0)}개
- 발견한 레시피: {stats.get('known_recipes', 0)}개

최근 관찰:
{obs_summary}

발견한 조작법:
{ctrl_summary}

발견한 엔티티:
{entity_summary}

참고할 목표 후보 (상태에 맞는 것을 골라줘):
1. Tab을 눌러 지도를 열고 근처의 색깔로 표시된 자원 패치를 찾아라.
2. 지도를 닫고 가장 가까운 철광석 패치로 WASD를 사용해 걸어가라.
3. 철광석 위에서 mouse_hold로 우클릭을 꾹 눌러 채굴해라.
4. 석재(돌)를 mouse_hold 우클릭 홀드로 채굴해라.
5. 석탄을 mouse_hold 우클릭 홀드로 채굴해라.
6. E를 눌러 인벤토리를 열고 돌 화로를 조합해라 (석재 5개 필요).
7. 돌 화로를 바닥에 설치하고 석탄을 연료로 넣어라.
8. 돌 화로에 철광석을 넣어 철판으로 제련해라.
9. 철 기어 휠을 조합해라 (철판 2개씩).
10. 버너 채굴기를 조합해서 철광석 패치 위에 설치해라.
11. T를 눌러 기술 트리를 열고 자동화 연구를 시작해라.

한글 1~2문장으로 다음 게임 목표만 답해줘. 설명이나 부연 없이 목표 문장만 짧게."""


def build_summary_request(
    observations: list[dict],
    known_controls: list[dict],
) -> str:
    """Build prompt for Brain experience summary (Feature B)."""
    obs_lines = []
    for o in observations:
        success_mark = ""
        if o.get("success") is not None:
            success_mark = " ✓" if o["success"] == 1 else " ✗"
        obs_lines.append(
            f"  - [{o['action_type']} {o['action_args']}]{success_mark} {o['thought'][:60]}"
        )
    obs_text = "\n".join(obs_lines) if obs_lines else "  없음."

    ctrl_lines = [f"  - {c['key']}: {c['effect']} (conf: {c['confidence']:.1f})"
                  for c in known_controls[:15]]
    ctrl_text = "\n".join(ctrl_lines) if ctrl_lines else "  없음."

    return f"""나는 팩토리오 게임을 자동 플레이하는 AI 에이전트를 만들고 있어.
아래는 최근 관찰 기록과 학습된 조작법이야.

최근 관찰 ({len(observations)}개):
{obs_text}

학습된 조작법:
{ctrl_text}

이 관찰들에서 에이전트가 배운 패턴, 전략, 실패/성공 경험을 한글 3~5문장으로 요약해줘.
요약만 답해줘."""


def build_wiki_request(topic: str) -> str:
    return f"""팩토리오 게임에 대해 질문이 있어: {topic}

다음 내용을 포함해서 한글로 간결하게 답해줘:
- 무엇인지
- 어떻게 사용/건설하는지
- 필요한 레시피나 조건
- 유용한 팁

300자 이내로 실용적인 게임플레이 정보만 답해줘."""
