from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.repositories.mysql_repo import MySQLRepository


DEFAULT_MAX_CONVERSATIONS = 10
DEFAULT_MAX_MESSAGES = 10
DEFAULT_CLEANUP_STALE_DAYS = 7
DEFAULT_CLEANUP_BATCH_SIZE = 5


@dataclass
class ConversationContext:
    conversation: Dict[str, Any]
    messages: List[Dict[str, Any]]


class ConversationService:
    def __init__(
        self,
        repo: ConversationRepository | None = None,
        *,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        cleanup_stale_days: int = DEFAULT_CLEANUP_STALE_DAYS,
        cleanup_batch_size: int = DEFAULT_CLEANUP_BATCH_SIZE,
    ) -> None:
        self.repo = repo or MySQLRepository().conversations
        self.max_conversations = max_conversations
        self.max_messages = max_messages
        self.cleanup_stale_days = cleanup_stale_days
        self.cleanup_batch_size = cleanup_batch_size

    def ensure_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.repo.ensure_conversation(
            user_id=user_id,
            scope=scope,
            scope_key=scope_key,
            title=title,
            keep_latest=self.max_conversations,
        )

    def create_new_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.repo.create_conversation(
            user_id=user_id,
            scope=scope,
            scope_key=scope_key,
            title=title,
            keep_latest=self.max_conversations,
        )

    def delete_conversation(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> bool:
        return self.repo.delete_owned_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )

    def get_conversation_context(
        self, *, user_id: int, conversation_id: int
    ) -> ConversationContext:
        context = self.repo.get_owned_conversation_context(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if context is None:
            raise ValueError("conversation_not_found")
        return ConversationContext(
            conversation=context["conversation"],
            messages=context["messages"],
        )

    def list_conversations(
        self,
        *,
        user_id: int,
        scope: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        return self.repo.list_conversations(
            user_id=user_id,
            scope=scope,
            page=page,
            page_size=page_size,
        )

    def append_message_pair(
        self,
        *,
        user_id: int,
        conversation_id: Optional[int],
        scope: str,
        scope_key: Optional[str],
        user_message: str,
        assistant_content: str,
        assistant_thinking: str = "",
        sources: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        parent_message_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.repo.append_message_pair(
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            scope_key=scope_key,
            user_message=user_message,
            assistant_content=assistant_content,
            assistant_thinking=assistant_thinking,
            sources=sources,
            attachments=attachments,
            parent_message_id=parent_message_id,
            title=title or self._derive_title(user_message),
            max_messages=self.max_messages,
            max_conversations=self.max_conversations,
        )

    def delete_message(self, *, user_id: int, message_id: int) -> Dict[str, Any]:
        result = self.repo.delete_owned_message_branch(
            user_id=user_id,
            message_id=message_id,
        )
        if result is None:
            raise ValueError("message_not_found")
        return result

    def regenerate_from_message(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> Dict[str, Any]:
        result = self.repo.prepare_owned_regeneration(
            user_id=user_id,
            message_id=message_id,
        )
        if result is None:
            raise ValueError("message_not_found")
        return result

    def cleanup_stale_conversations(self) -> int:
        return self.repo.cleanup_stale_conversations(
            stale_days=self.cleanup_stale_days,
            limit=self.cleanup_batch_size,
        )

    @staticmethod
    def _derive_title(message: str) -> str:
        text = (message or "").strip().replace("\n", " ")
        if not text:
            return "新对话"
        return text[:60]

    @staticmethod
    def _build_preview(message: str) -> str:
        text = (message or "").strip().replace("\n", " ")
        return text[:200]
