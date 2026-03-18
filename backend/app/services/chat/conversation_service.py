from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
        repo: Optional[MySQLRepository] = None,
        *,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        cleanup_stale_days: int = DEFAULT_CLEANUP_STALE_DAYS,
        cleanup_batch_size: int = DEFAULT_CLEANUP_BATCH_SIZE,
    ) -> None:
        self.repo = repo or MySQLRepository()
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
        conversation = self.repo.get_or_create_conversation(
            user_id=user_id,
            scope=scope,
            scope_key=scope_key,
            title=title,
        )
        self.repo.touch_conversation(conversation["id"])
        self._trim_user_conversations(user_id)
        return (
            self.repo.get_conversation_by_id(conversation["id"], user_id=user_id)
            or conversation
        )

    def create_new_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """强制创建新会话（不复用已有会话）。"""
        conversation = self.repo.create_conversation(
            user_id=user_id,
            scope=scope,
            scope_key=scope_key,
            title=title,
        )
        self.repo.touch_conversation(conversation["id"])
        self._trim_user_conversations(user_id)
        return (
            self.repo.get_conversation_by_id(conversation["id"], user_id=user_id)
            or conversation
        )

    def delete_conversation(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> bool:
        """删除指定会话及其所有消息。"""
        return self.repo.delete_conversation_by_id(
            conversation_id,
            user_id=user_id,
        )

    def get_conversation_context(
        self, *, user_id: int, conversation_id: int
    ) -> ConversationContext:
        conversation = self.repo.get_conversation_by_id(
            conversation_id, user_id=user_id
        )
        if conversation is None:
            raise ValueError("conversation_not_found")
        self.repo.touch_conversation(conversation_id)
        messages = self.repo.list_chat_messages(conversation_id)
        return ConversationContext(conversation=conversation, messages=messages)

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
        conversation = self.ensure_conversation(
            user_id=user_id,
            scope=scope,
            scope_key=scope_key,
            title=title or self._derive_title(user_message),
        )
        if conversation_id and int(conversation["id"]) != int(conversation_id):
            existing = self.repo.get_conversation_by_id(
                conversation_id, user_id=user_id
            )
            if existing is not None:
                conversation = existing

        self.repo.touch_conversation(conversation["id"])

        user_row = self.repo.create_chat_message(
            conversation_id=conversation["id"],
            role="user",
            content=user_message,
            thinking="",
            sources=[],
            attachments=attachments or [],
            status="done",
            parent_message_id=parent_message_id,
        )
        assistant_row = self.repo.create_chat_message(
            conversation_id=conversation["id"],
            role="assistant",
            content=assistant_content,
            thinking=assistant_thinking,
            sources=sources or [],
            attachments=attachments or [],
            status="done",
            parent_message_id=user_row["id"],
        )
        self.repo.refresh_conversation_stats(
            conversation["id"],
            title=conversation.get("title") or self._derive_title(user_message),
            last_message_preview=self._build_preview(assistant_content or user_message),
        )
        self._trim_conversation_messages(conversation["id"])
        self._trim_user_conversations(user_id)
        latest_conversation = (
            self.repo.get_conversation_by_id(conversation["id"], user_id=user_id)
            or conversation
        )
        latest_messages = self.repo.list_chat_messages(conversation["id"])
        return {
            "conversation": latest_conversation,
            "user_message": user_row,
            "assistant_message": assistant_row,
            "messages": latest_messages,
        }

    def delete_message(self, *, user_id: int, message_id: int) -> Dict[str, Any]:
        message = self.repo.get_chat_message(message_id, user_id=user_id)
        if message is None:
            raise ValueError("message_not_found")
        conversation_id = int(message["conversation_id"])
        deleted_ids = self.repo.delete_message_branch(message_id)
        self.repo.refresh_conversation_stats(conversation_id)
        context = self.get_conversation_context(
            user_id=user_id, conversation_id=conversation_id
        )
        return {
            "deleted_ids": deleted_ids,
            "conversation": context.conversation,
            "messages": context.messages,
        }

    def regenerate_from_message(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> Dict[str, Any]:
        message = self.repo.get_chat_message(message_id, user_id=user_id)
        if message is None:
            raise ValueError("message_not_found")
        conversation_id = int(message["conversation_id"])
        deleted_ids = self.repo.delete_messages_after(message_id)
        self.repo.refresh_conversation_stats(conversation_id)
        context = self.get_conversation_context(
            user_id=user_id, conversation_id=conversation_id
        )
        return {
            "deleted_ids": deleted_ids,
            "conversation": context.conversation,
            "messages": context.messages,
            "target_message": message,
        }

    def cleanup_stale_conversations(self) -> int:
        return self.repo.cleanup_stale_conversations(
            stale_days=self.cleanup_stale_days,
            limit=self.cleanup_batch_size,
        )

    def _trim_conversation_messages(self, conversation_id: int) -> None:
        self.repo.trim_conversation_messages(
            conversation_id=conversation_id,
            keep_latest=self.max_messages,
        )
        self.repo.refresh_conversation_stats(conversation_id)

    def _trim_user_conversations(self, user_id: int) -> None:
        self.repo.trim_user_conversations(
            user_id=user_id,
            keep_latest=self.max_conversations,
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
