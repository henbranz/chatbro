import os
import tempfile
import unittest
from uuid import uuid4


TEST_DB = tempfile.NamedTemporaryFile(prefix="chatbro-groups-", suffix=".db", delete=False)
TEST_DB.close()
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.name}"

from fastapi import BackgroundTasks, HTTPException  # noqa: E402

import backend.main as api  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402


class GroupChatApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        api.time.sleep = lambda _seconds: None

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            os.unlink(TEST_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self) -> None:
        self.db = SessionLocal()
        suffix = uuid4().hex[:8]
        self.owner = api.register(
            api.AuthRequest(username=f"owner_{suffix}", email=f"owner_{suffix}@example.com", password="pass"),
            db=self.db,
        )
        self.member = api.register(
            api.AuthRequest(username=f"member_{suffix}", email=f"member_{suffix}@example.com", password="pass"),
            db=self.db,
        )
        self.outsider = api.register(
            api.AuthRequest(username=f"outsider_{suffix}", email=f"outsider_{suffix}@example.com", password="pass"),
            db=self.db,
        )

    def tearDown(self) -> None:
        self.db.close()

    def run_background_tasks(self, tasks: BackgroundTasks) -> None:
        for task in tasks.tasks:
            task.func(*task.args, **task.kwargs)

    def test_group_invite_accept_messages_and_permissions(self) -> None:
        group = api.create_group_chat(
            api.GroupCreateRequest(user_id=self.owner.id, name="Family planning"),
            db=self.db,
        )
        self.assertEqual(group.name, "Family planning")
        self.assertEqual(group.role, "owner")
        self.assertEqual(group.member_count, 1)

        invitation = api.invite_user_to_group(
            group.id,
            api.GroupInviteRequest(inviter_user_id=self.owner.id, invited_email=self.member.email),
            db=self.db,
        )
        self.assertEqual(invitation.status, "pending")
        self.assertEqual(invitation.invited_email, self.member.email)

        with self.assertRaises(HTTPException) as duplicate_invite:
            api.invite_user_to_group(
                group.id,
                api.GroupInviteRequest(inviter_user_id=self.owner.id, invited_email=self.member.email),
                db=self.db,
            )
        self.assertEqual(duplicate_invite.exception.status_code, 409)

        pending = api.get_my_invitations(user_id=self.member.id, db=self.db)
        self.assertEqual([item.id for item in pending], [invitation.id])

        accepted = api.accept_group_invitation(
            invitation.id,
            api.InvitationActionRequest(user_id=self.member.id),
            db=self.db,
        )
        self.assertEqual(accepted.status, "accepted")

        groups_for_member = api.get_my_groups(user_id=self.member.id, db=self.db)
        self.assertEqual([item.id for item in groups_for_member], [group.id])

        member_search = api.search(user_id=self.owner.id, q=self.member.email, limit=50, db=self.db)
        self.assertTrue(any(result.group_id == group.id for result in member_search.group_members))

        typing_update = api.update_group_typing_status(
            group.id,
            api.GroupTypingRequest(user_id=self.member.id, is_typing=True),
            db=self.db,
        )
        self.assertTrue(typing_update["success"])
        typing_seen_by_owner = api.get_group_typing_statuses(group.id, user_id=self.owner.id, db=self.db)
        self.assertEqual([status.user_id for status in typing_seen_by_owner], [self.member.id])
        typing_seen_by_member = api.get_group_typing_statuses(group.id, user_id=self.member.id, db=self.db)
        self.assertEqual(typing_seen_by_member, [])

        with self.assertRaises(HTTPException) as outsider_typing:
            api.get_group_typing_statuses(group.id, user_id=self.outsider.id, db=self.db)
        self.assertEqual(outsider_typing.exception.status_code, 403)

        other_group = api.create_group_chat(
            api.GroupCreateRequest(user_id=self.owner.id, name="Other group"),
            db=self.db,
        )
        self.assertEqual(api.get_group_typing_statuses(other_group.id, user_id=self.owner.id, db=self.db), [])

        api.update_group_typing_status(
            group.id,
            api.GroupTypingRequest(user_id=self.member.id, is_typing=False),
            db=self.db,
        )
        self.assertEqual(api.get_group_typing_statuses(group.id, user_id=self.owner.id, db=self.db), [])

        api.update_group_typing_status(
            group.id,
            api.GroupTypingRequest(user_id=self.member.id, is_typing=True),
            db=self.db,
        )
        expired_status = (
            self.db.query(api.GroupTypingStatus)
            .filter(api.GroupTypingStatus.group_id == group.id, api.GroupTypingStatus.user_id == self.member.id)
            .first()
        )
        expired_status.updated_at = api.datetime.utcnow() - api.timedelta(
            seconds=api.GROUP_TYPING_TIMEOUT_SECONDS + 1
        )
        self.db.commit()
        self.assertEqual(api.get_group_typing_statuses(group.id, user_id=self.owner.id, db=self.db), [])
        self.db.expire_all()

        api.update_group_typing_status(
            group.id,
            api.GroupTypingRequest(user_id=self.member.id, is_typing=True),
            db=self.db,
        )

        with self.assertRaises(HTTPException) as outsider_read:
            api.get_group_messages(group.id, user_id=self.outsider.id, db=self.db)
        self.assertEqual(outsider_read.exception.status_code, 403)

        with self.assertRaises(HTTPException) as outsider_send:
            api.create_group_message(
                group.id,
                api.GroupMessageCreateRequest(sender_id=self.outsider.id, content="Can I join?"),
                background_tasks=BackgroundTasks(),
                db=self.db,
            )
        self.assertEqual(outsider_send.exception.status_code, 403)

        tasks = BackgroundTasks()
        created = api.create_group_message(
            group.id,
            api.GroupMessageCreateRequest(sender_id=self.member.id, content="Hello team"),
            background_tasks=tasks,
            db=self.db,
        )
        self.assertEqual(len(created.messages), 1)
        self.assertEqual(created.messages[0].sender_type, "user")
        self.assertEqual(api.get_group_typing_statuses(group.id, user_id=self.owner.id, db=self.db), [])

        after_user_message = api.get_new_group_messages(
            group.id,
            user_id=self.owner.id,
            after_id=created.messages[0].id,
            limit=100,
            db=self.db,
        )
        self.assertEqual(after_user_message, [])

        self.run_background_tasks(tasks)
        after_bot_reply = api.get_new_group_messages(
            group.id,
            user_id=self.owner.id,
            after_id=created.messages[0].id,
            limit=100,
            db=self.db,
        )
        self.assertEqual(len(after_bot_reply), 1)
        self.assertEqual(after_bot_reply[0].sender_type, "bot")

        group_message_search = api.search(user_id=self.owner.id, q="Hello team", limit=50, db=self.db)
        self.assertTrue(any(result.group_id == group.id for result in group_message_search.group_messages))

        after_latest = api.get_new_group_messages(
            group.id,
            user_id=self.owner.id,
            after_id=after_bot_reply[0].id,
            limit=100,
            db=self.db,
        )
        self.assertEqual(after_latest, [])

    def test_decline_invitation(self) -> None:
        group = api.create_group_chat(
            api.GroupCreateRequest(user_id=self.owner.id, name="Decline test"),
            db=self.db,
        )
        invitation = api.invite_user_to_group(
            group.id,
            api.GroupInviteRequest(inviter_user_id=self.owner.id, invited_email=self.outsider.email),
            db=self.db,
        )
        declined = api.decline_group_invitation(
            invitation.id,
            api.InvitationActionRequest(user_id=self.outsider.id),
            db=self.db,
        )
        self.assertEqual(declined.status, "declined")
        self.assertEqual(api.get_my_groups(user_id=self.outsider.id, db=self.db), [])

    def test_existing_single_user_chat_flow_still_works(self) -> None:
        tasks = BackgroundTasks()
        created = api.create_message(
            api.MessageCreateRequest(sender_id=self.owner.id, content="Hello Chat Bro"),
            background_tasks=tasks,
            db=self.db,
        )
        self.assertEqual(created.role, "user")
        self.assertEqual(created.conversation_id, f"default-{self.owner.id}")

        messages = api.get_messages(
            user_id=self.owner.id,
            conversation_id=created.conversation_id,
            after_id=None,
            limit=100,
            db=self.db,
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, created.id)

        self.run_background_tasks(tasks)
        messages_after_bot = api.get_messages(
            user_id=self.owner.id,
            conversation_id=created.conversation_id,
            after_id=None,
            limit=100,
            db=self.db,
        )
        self.assertEqual(len(messages_after_bot), 2)
        self.assertEqual(messages_after_bot[-1].role, "assistant")

    def test_registration_requires_unique_email(self) -> None:
        suffix = uuid4().hex[:8]
        user = api.register(
            api.AuthRequest(username=f"email_one_{suffix}", email=f"same_{suffix}@example.com", password="pass"),
            db=self.db,
        )
        self.assertEqual(user.email, f"same_{suffix}@example.com")

        updated = api.update_user_profile(
            user.id,
            api.UserUpdateRequest(username=f"email_owner_{suffix}", email=f"updated_{suffix}@example.com"),
            db=self.db,
        )
        self.assertEqual(updated.username, f"email_owner_{suffix}")
        self.assertEqual(updated.email, f"updated_{suffix}@example.com")

        with self.assertRaises(HTTPException) as duplicate_email:
            api.register(
                api.AuthRequest(username=f"email_two_{suffix}", email=f"updated_{suffix}@example.com", password="pass"),
                db=self.db,
            )
        self.assertEqual(duplicate_email.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
