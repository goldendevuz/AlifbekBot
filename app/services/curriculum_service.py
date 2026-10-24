"""Curriculum and educational content management service for Alifbo core."""
import json
import logging
from typing import Any, Dict, List, Optional
from app.database import get_connection
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class CurriculumService:
    @staticmethod
    def get_curriculum() -> List[Dict[str, Any]]:
        """Fetch all published or draft curriculum modules with their nested lessons."""
        conn = get_connection()
        try:
            modules = conn.execute(
                "SELECT * FROM curriculum_modules ORDER BY order_num ASC"
            ).fetchall()

            result = []
            for m in modules:
                m_dict = dict(m)
                m_dict["is_published"] = bool(m_dict["is_published"])

                lessons = conn.execute(
                    "SELECT * FROM curriculum_lessons WHERE module_id = ? ORDER BY order_num ASC",
                    (m["id"],),
                ).fetchall()

                lesson_list = []
                for les in lessons:
                    l_dict = dict(les)
                    if l_dict.get("quiz_data"):
                        try:
                            l_dict["quiz_data"] = json.loads(l_dict["quiz_data"])
                        except Exception:
                            l_dict["quiz_data"] = None
                    lesson_list.append(l_dict)

                m_dict["lessons"] = lesson_list
                result.append(m_dict)

            return result
        finally:
            conn.close()

    @staticmethod
    def save_module(
        module_id: str,
        title: str,
        description: str,
        level: str = "beginner",
        order_num: int = 1,
        is_published: bool = True,
        actor: str = "superadmin",
    ) -> Dict[str, Any]:
        """Create or update a curriculum module."""
        conn = get_connection()
        try:
            existing = conn.execute("SELECT * FROM curriculum_modules WHERE id = ?", (module_id,)).fetchone()
            rollback_payload = None
            if existing:
                rollback_payload = {
                    "operation": "restore",
                    "id": existing["id"],
                    "title": existing["title"],
                    "description": existing["description"],
                    "level": existing["level"],
                    "order_num": existing["order_num"],
                    "is_published": existing["is_published"],
                }

            conn.execute(
                """
                INSERT OR REPLACE INTO curriculum_modules (id, title, description, level, order_num, is_published)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (module_id, title, description, level, order_num, 1 if is_published else 0),
            )
            conn.commit()

            AuditService.record_action(
                actor=actor,
                action="module_update" if existing else "module_create",
                target_type="curriculum_module",
                target_id=module_id,
                details={"title": title, "level": level},
                rollback_payload=rollback_payload,
            )

            return {
                "id": module_id,
                "title": title,
                "description": description,
                "level": level,
                "order_num": order_num,
                "is_published": is_published,
                "message": "Module saved successfully",
            }
        finally:
            conn.close()

    @staticmethod
    def save_lesson(
        lesson_id: str,
        module_id: str,
        title: str,
        letter_char: Optional[str] = None,
        phonetic_guide: Optional[str] = None,
        audio_url: Optional[str] = None,
        cyrillic_equiv: Optional[str] = None,
        old_latin_equiv: Optional[str] = None,
        rules_content: Optional[str] = None,
        quiz_data: Optional[Dict[str, Any]] = None,
        order_num: int = 1,
        actor: str = "superadmin",
    ) -> Dict[str, Any]:
        """Create or update a curriculum lesson."""
        conn = get_connection()
        try:
            existing = conn.execute("SELECT * FROM curriculum_lessons WHERE id = ?", (lesson_id,)).fetchone()
            rollback_payload = None
            if existing:
                rollback_payload = {
                    "operation": "restore",
                    "id": existing["id"],
                    "module_id": existing["module_id"],
                    "title": existing["title"],
                    "letter_char": existing["letter_char"],
                    "phonetic_guide": existing["phonetic_guide"],
                    "audio_url": existing["audio_url"],
                    "cyrillic_equiv": existing["cyrillic_equiv"],
                    "old_latin_equiv": existing["old_latin_equiv"],
                    "rules_content": existing["rules_content"],
                    "quiz_data": json.loads(existing["quiz_data"]) if existing["quiz_data"] else None,
                    "order_num": existing["order_num"],
                }

            conn.execute(
                """
                INSERT OR REPLACE INTO curriculum_lessons 
                (id, module_id, title, letter_char, phonetic_guide, audio_url, cyrillic_equiv, old_latin_equiv, rules_content, quiz_data, order_num)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson_id,
                    module_id,
                    title,
                    letter_char,
                    phonetic_guide,
                    audio_url,
                    cyrillic_equiv,
                    old_latin_equiv,
                    rules_content,
                    json.dumps(quiz_data) if quiz_data else None,
                    order_num,
                ),
            )
            conn.commit()

            AuditService.record_action(
                actor=actor,
                action="lesson_update" if existing else "lesson_create",
                target_type="curriculum_lesson",
                target_id=lesson_id,
                details={"title": title, "module_id": module_id, "letter_char": letter_char},
                rollback_payload=rollback_payload,
            )

            return {
                "id": lesson_id,
                "module_id": module_id,
                "title": title,
                "letter_char": letter_char,
                "message": "Lesson saved successfully",
            }
        finally:
            conn.close()

    @staticmethod
    def delete_lesson(lesson_id: str, actor: str = "superadmin") -> bool:
        conn = get_connection()
        try:
            existing = conn.execute("SELECT * FROM curriculum_lessons WHERE id = ?", (lesson_id,)).fetchone()
            if not existing:
                return False

            rollback_payload = {
                "operation": "restore",
                "id": existing["id"],
                "module_id": existing["module_id"],
                "title": existing["title"],
                "letter_char": existing["letter_char"],
                "phonetic_guide": existing["phonetic_guide"],
                "audio_url": existing["audio_url"],
                "cyrillic_equiv": existing["cyrillic_equiv"],
                "old_latin_equiv": existing["old_latin_equiv"],
                "rules_content": existing["rules_content"],
                "quiz_data": json.loads(existing["quiz_data"]) if existing["quiz_data"] else None,
                "order_num": existing["order_num"],
            }

            conn.execute("DELETE FROM curriculum_lessons WHERE id = ?", (lesson_id,))
            conn.commit()

            AuditService.record_action(
                actor=actor,
                action="lesson_delete",
                target_type="curriculum_lesson",
                target_id=lesson_id,
                details={"deleted_title": existing["title"]},
                rollback_payload=rollback_payload,
            )
            return True
        finally:
            conn.close()
