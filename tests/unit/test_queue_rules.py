from backend.source_adapters.lottery_toolman.html_parser import find_content_root, parse_html
from backend.source_adapters.lottery_toolman.queue_rules import collect_queue


def _collect(html: str):
    root = find_content_root(parse_html(html))
    assert root is not None
    return collect_queue(root, "https://www.bilibili.com/read/cv52163098")


def test_queue_skips_pinned_and_aggregate_links_and_preserves_order():
    result = _collect(
        """
        <article class="opus-module-content">
          <p>置顶抽奖 <a href="https://www.bilibili.com/opus/900000001">置顶</a></p>
          <p>奖品说明 <a href="https://www.bilibili.com/opus/900000002">置顶说明</a></p>
          <p>1、→ 2026年8月10日 <a href="https://www.bilibili.com/opus/100000001">第一条</a></p>
          <p>2、→ 2026年8月11日 <a href="https://www.bilibili.com/opus/100000002">第二条</a></p>
          <p><a href="https://www.bilibili.com/opus/100000003">官方抽奖合集（全部版）</a></p>
          <p>重复 <a href="https://t.bilibili.com/100000002?spm_id_from=x">第二条旧链接</a></p>
        </article>
        """
    )
    assert result.stats.start_mode == "sequence-link"
    assert result.stats.started_after_pinned is True
    assert result.stats.aggregate_excluded == 1
    assert [item.dynamic_id for item in result.items] == ["100000001", "100000002"]
    assert [item.source_position for item in result.items] == [1, 2]


def test_queue_uses_new_link_before_sequence_link():
    result = _collect(
        """
        <div class="opus-module-content">
          <p>置顶抽奖</p>
          <p>新的 → 2026年8月12日 <a href="/opus/200000001">最新</a></p>
          <p>1、→ 2026年8月11日 <a href="/opus/200000002">旧起点</a></p>
          <p>2、→ 2026年8月10日 <a href="/opus/200000003">另一条</a></p>
        </div>
        """
    )
    assert result.stats.start_mode == "new-link"
    assert [item.dynamic_id for item in result.items] == [
        "200000001",
        "200000002",
        "200000003",
    ]


def test_queue_without_pinned_section_starts_from_first_and_normalizes_t_url():
    result = _collect(
        """
        <div class="opus-module-content">
          <p><a href="https://t.bilibili.com/300000001#fragment">动态一</a></p>
          <p><a href="https://www.bilibili.com/opus/300000002?foo=bar">动态二</a></p>
        </div>
        """
    )
    assert result.stats.start_mode == "from-first"
    assert [item.canonical_url for item in result.items] == [
        "https://www.bilibili.com/opus/300000001",
        "https://www.bilibili.com/opus/300000002",
    ]


def test_mixed_collection_skips_previous_portal_and_charge_section():
    root = find_content_root(
        parse_html(
            """
            <article class="opus-module-content">
              <p>上期传送门 <a href="/opus/400000000">上一期合集</a></p>
              <p>充电抽奖：关注，充电，即可参与</p>
              <p>1、→ 2026年8月20日 充电，关注、转发、点赞
                <a href="/opus/400000001">充电</a>
              </p>
              <p>预约抽奖：预约，即可参与</p>
              <p>2、→ 2026年8月21日 <a href="/opus/400000002">预约抽奖</a></p>
              <p>互动抽奖：关注、转发、点赞</p>
              <p>3、→ 2026年8月22日 <a href="/opus/400000003">互动抽奖</a></p>
            </article>
            """
        )
    )
    assert root is not None

    result = collect_queue(
        root,
        "https://www.bilibili.com/read/cv52565444",
        include_sections={"reservation", "interactive"},
    )

    assert [item.dynamic_id for item in result.items] == ["400000002", "400000003"]
    assert [item.source_section for item in result.items] == ["reservation", "interactive"]


def test_entry_participation_markers_update_section_without_headings():
    root = find_content_root(
        parse_html(
            """
            <article class="opus-module-content">
              <p>1、→ 2026年8月20日 充电，关注、转发、点赞 <a href="/opus/500000001">充电</a></p>
              <p>2、→ 2026年8月21日 预约，即可参与 <a href="/opus/500000002">预约</a></p>
              <p>3、→ 2026年8月22日 关注、转发、点赞 <a href="/opus/500000003">互动</a></p>
            </article>
            """
        )
    )
    assert root is not None
    result = collect_queue(
        root,
        "https://www.bilibili.com/read/cv52565444",
        include_sections={"reservation", "interactive"},
    )
    assert [item.dynamic_id for item in result.items] == ["500000002", "500000003"]
    assert [item.source_section for item in result.items] == ["reservation", "interactive"]
