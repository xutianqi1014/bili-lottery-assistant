import re

from backend.activity_engine.models import ParticipationRequirements

from .comment_rules import extract_comment_instruction
from .numbers import parse_count


class RequirementParser:
    _topic_pattern = re.compile(r"#[^#\r\n]{1,80}#")
    _number_token = (
        r"(?:\d{1,3}|[零〇一壹二两貳贰三叁四肆五伍六陆陸七柒八捌九玖十拾百佰千仟]+)"
    )
    _mention_patterns = (
        re.compile(
            rf"(?:@|艾特|at)\s*({_number_token})\s*"
            r"(?:名|位|个|人)?\s*(?:好友|朋友|人)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:@|艾特|at)\s*(?:好友|朋友|用户)\s*({_number_token})\s*"
            r"(?:名|位|个|人)?",
            re.IGNORECASE,
        ),
    )
    _action_patterns = (
        ("comment", re.compile(r"评论|留言|分享你的|分享您|聊聊|说说|谈谈")),
        ("repost", re.compile(r"转发")),
        ("like", re.compile(r"点赞|点个赞")),
        ("follow", re.compile(r"关注")),
    )
    _mention_limit = 20

    def parse(self, visible_text: str) -> ParticipationRequirements:
        topics = tuple(dict.fromkeys(self._topic_pattern.findall(visible_text)))
        mention_count = self._mention_count(visible_text)
        actions = tuple(
            name for name, pattern in self._action_patterns if pattern.search(visible_text)
        )
        evidence = tuple(f"REQUIREMENT_{action.upper()}" for action in actions)
        limit_exceeded = mention_count > self._mention_limit
        if mention_count:
            evidence += ("REQUIREMENT_MENTION_COUNT",)
        if limit_exceeded:
            evidence += ("REQUIREMENT_MENTION_LIMIT_EXCEEDED",)
        return ParticipationRequirements(
            required_topics=topics,
            required_mention_count=mention_count,
            comment_instruction=extract_comment_instruction(visible_text),
            required_actions=actions,
            mention_limit_exceeded=limit_exceeded,
            evidence_codes=evidence,
        )

    @classmethod
    def _mention_count(cls, text: str) -> int:
        compact = "".join(text.split())
        for pattern in cls._mention_patterns:
            match = pattern.search(compact)
            if match is not None:
                return parse_count(match.group(1))
        return 0
