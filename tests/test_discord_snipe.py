"""Regression tests for the Discord /snipe feature."""
from unittest import mock
import asyncio
import time

import discord
from discord import app_commands

import services.messaging as messaging_mod


class _FakeAuthor:
    def __init__(self, name, uid):
        self._name = name
        self.id = uid

    def __str__(self):
        return self._name


class _FakeMessage:
    def __init__(self, channel_id, content, author_name="someone", author_id=1, attachments=None):
        self.channel = mock.Mock(id=channel_id)
        self.content = content
        self.author = _FakeAuthor(author_name, author_id)
        self.attachments = attachments or []


def _build_bot():
    """Construct the real Discord client/tree without making a network call."""
    bot = messaging_mod.JarvisDiscordBot()
    captured_trees = []
    real_tree_cls = app_commands.CommandTree

    def _capturing_tree(client, *a, **kw):
        tree = real_tree_cls(client, *a, **kw)
        captured_trees.append(tree)
        return tree

    with mock.patch("services.messaging.DISCORD_BOT_TOKEN", "fake-token"), \
         mock.patch.object(app_commands, "CommandTree", side_effect=_capturing_tree), \
         mock.patch.object(discord.Client, "run", side_effect=discord.errors.LoginFailure("fake")):
        bot.start()

    assert captured_trees, "CommandTree was never constructed"
    return bot, captured_trees[0]


def test_snipe_command_registered():
    _, tree = _build_bot()
    assert tree.get_command("snipe") is not None


def test_on_message_delete_populates_snipe_cache():
    bot, _ = _build_bot()
    handler = bot._client.on_message_delete
    msg = _FakeMessage(channel_id=42, content="oops, deleting this", author_name="Alice")

    asyncio.run(handler(msg))

    entry = bot._snipe_cache[42]
    assert entry["content"] == "oops, deleting this"
    assert entry["author"] == "Alice"
    assert entry["attachments"] == []


def test_snipe_command_reports_nothing_when_cache_empty():
    bot, tree = _build_bot()
    snipe_cmd = tree.get_command("snipe")

    interaction = mock.AsyncMock()
    interaction.channel_id = 999
    interaction.user.id = 1

    asyncio.run(snipe_cmd.callback(interaction))

    sent_text = interaction.response.send_message.call_args[0][0]
    assert "Nothing to snipe" in sent_text


def test_snipe_command_returns_cached_deleted_message():
    bot, tree = _build_bot()
    snipe_cmd = tree.get_command("snipe")
    bot._snipe_cache[555] = {
        "content": "the secret message", "author": "Bob", "author_id": 2,
        "deleted_at": time.time(), "attachments": [],
    }

    interaction = mock.AsyncMock()
    interaction.channel_id = 555
    interaction.user.id = 1

    asyncio.run(snipe_cmd.callback(interaction))

    sent_text = interaction.response.send_message.call_args[0][0]
    assert "Bob" in sent_text
    assert "the secret message" in sent_text


def test_snipe_command_expires_after_ttl():
    bot, tree = _build_bot()
    snipe_cmd = tree.get_command("snipe")
    bot._snipe_cache[777] = {
        "content": "old news", "author": "Carol", "author_id": 3,
        "deleted_at": time.time() - messaging_mod._SNIPE_TTL_SECONDS - 1,
        "attachments": [],
    }

    interaction = mock.AsyncMock()
    interaction.channel_id = 777
    interaction.user.id = 1

    asyncio.run(snipe_cmd.callback(interaction))

    sent_text = interaction.response.send_message.call_args[0][0]
    assert "Nothing to snipe" in sent_text
    assert "old news" not in sent_text


def test_snipe_command_respects_authorization():
    bot, tree = _build_bot()
    snipe_cmd = tree.get_command("snipe")
    bot._snipe_cache[42] = {
        "content": "private stuff", "author": "Dave", "author_id": 4,
        "deleted_at": time.time(), "attachments": [],
    }

    interaction = mock.AsyncMock()
    interaction.channel_id = 42
    interaction.user.id = 12345

    with mock.patch.object(bot, "_authorized", return_value=False):
        asyncio.run(snipe_cmd.callback(interaction))

    sent_text = interaction.response.send_message.call_args[0][0]
    assert sent_text == "Unauthorized."
