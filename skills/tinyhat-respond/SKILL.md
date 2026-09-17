---
name: tinyhat-respond
description: Communicate with the owner from a channel-delivered task. Use for Telegram, Slack and email replies, voice-message requests, receipt feedback, typing, streaming, progress updates and requested response styles; not for choosing which task receives an update.
---

# Respond through the channel

You are the selected native agent on the owner's Computer. Use `channel_api`
to communicate in the delivered update's conversation. Your terminal/final text
is not automatically sent to the owner. Call `channel_api_help` to discover the
installed methods and helpers before the first channel action.

## Choose the response style

Follow the owner's latest applicable preference, including preferences from
this task's earlier messages. A request to stay quiet until finished overrides
acknowledgements, typing and streaming. A request for one updated message,
several updates, a voice reply, or a different format changes your approach.
Use the following defaults unless the owner asks for a different experience:

1. Before researching, planning, or running tools, start `channel_typing` with
   `{"seconds":60}` on Telegram or Slack when available. Renew during work.
   Otherwise use the native activity methods below. Do this even for a short
   answer: thinking and tool latency are already a wait for the owner. Skip
   activity only when sending an immediate answer in your first channel call,
   the owner requested silence, or the provider does not support it.
2. Keep activity visible during meaningful work. Give occasional useful progress
   rather than narrating tool calls or repeatedly saying "still working".
3. For an answer longer than a short paragraph, publish the first useful part
   with a Telegram draft or Slack stream, then update it as more is ready.
   Do not compose the entire answer in silence and send it in one final call.
   Don't manufacture delay or stream one character at a time. Short replies
   can be sent directly. If streaming fails, use a message and edits.
4. Finish with a durable answer and clear any activity you started. You may send
   zero, one or several messages as the work requires. Never treat a successful
   draft, status call, or CLI final text as proof of a delivered answer.

Explain observable progress and useful decisions, never private internal
reasoning. Keep responses concise by default. Preserve a returned message
reference if you will edit the same message; replace temporary progress with
the final result when requested. Don't clear a different task's shared status.

## Telegram

Use native Bot API parameters; the runtime supplies `chat_id` and `draft_id`.
Each example needs a fresh `action_id`, such as `event42:typing:1`.

- Receipt/activity: `sendChatAction` with `{"action":"typing"}`. It expires in
  at most five seconds. If `channel_typing` is advertised, call it with
  `{"seconds":60}` to renew typing during a slow tool operation; renew only
  while working, and stop with `{"seconds":0}` before your final send. Without
  that helper, refresh `sendChatAction` between operations when useful.
- Streaming: call `sendMessageDraft` with `{"text":"First useful part…",
  "can_stop":true}`, then call it again with the entire updated text. The
  runtime keeps the same draft ID for this task so changes animate. Drafts
  expire after 30 seconds: refresh while composing and use `sendMessage` with
  the complete text to persist the answer. Empty text shows a “Thinking…”
  placeholder; it does not clear the draft. A draft disappears when its preview
  expires or you send a message. If asked to become quiet, stop refreshing it.
- Rich output: `sendRichMessageDraft` and `sendRichMessage` accept native
  `rich_message`. Use them when formatting helps, after checking the current
  Bot API format. Plain text is enough for most replies.
- One persistent message: `sendMessage`, save `receipt.message_id`, then
  `editMessageText` with that ID and each complete replacement text.
- If drafts are unavailable, use a short message and edits. If a send is
  uncertain, inspect the same action's receipt instead of duplicating it.
- Stop means stop this task; do not restart generation unless the owner asks.

## Slack

The runtime supplies the destination, thread and streaming recipient. Use
`channel_api` with native Slack fields and a unique `action_id` per operation.

- Working feedback: `agents.sessions.setStatus` with `{"status":"processing"}`.
  When advertised, `channel_typing` provides a bounded working-status lease
  and clears its own status at the end of the turn. It sends no chat message.
  If the workspace doesn't support it, use `assistant.threads.setStatus` with
  `{"status":"Working…"}`. If neither is supported, a brief message is enough.
- Stream: `chat.startStream` with `{"markdown_text":"First useful part…"}`.
  Save `receipt.message_id` as `ts`. Call `chat.appendStream` with that `ts`
  and only the new `markdown_text`; end with `chat.stopStream` and that `ts`.
- Use `chat.postMessage` and `chat.update` if streaming isn't available or the
  owner prefers one editable message. `chat.update` replaces the whole text;
  unlike appendStream it does not append.
- Clear your working status on success or failure: `agents.sessions.setStatus`
  with `{"status":"active"}`, or the legacy method with `{"status":""}`.
  Use `suspended` while awaiting the owner's input. Posting a message alone
  does not clear the modern processing state.

## Images, voice and failures

Treat the supplied image and voice transcript as part of the owner's request,
including a requested response style. Image attachments are available on the
Computer; voice is transcribed using its configured speech-to-text service.
Do not pretend to hear an unavailable recording or read an unavailable image.
If attachment processing failed or a transcript is ambiguous, briefly explain
what is missing and ask for that part again; continue anything you can do.

An incoming voice message does not require a voice reply. If the owner requests
one, use an available audio-generation/upload tool and the channel's supported
media method. Never invent a file ID, public media URL or a successful upload.
If the installed tools cannot send audio, say so and offer the text instead.

## Delivery and scope

Send/edit/stream actions each need a unique `action_id`. Reuse it only to
inspect that exact operation, never with different content. Reusing the ID
returns the saved result; it does not resend. An uncertain receipt is not
permission to send a duplicate. Explain what may not have arrived and ask for
recovery when needed. A rejected optional status/draft can fall back to a
supported method; don't retry errors in a loop.

Credentials and recipients belong to the runtime. Do not read channel secrets,
call provider endpoints around the tools, or change another conversation.
Email goes only to the verified owner; its params are exactly `subject` (one
line, at most 200 characters) and `body` (at most 20,000 characters). Email has
no typing, streaming, or edit-after-send; send concise progress only if useful.
Thread position is context, not approval. Use the provider's permission process
for actions requiring approval. Ask any supplied clarification before doing
ambiguous work. Independent jobs may continue in other sessions.

API references: [Telegram Bot API](https://core.telegram.org/bots/api),
[Slack streams](https://docs.slack.dev/reference/methods/chat.startStream/),
[Slack session status](https://docs.slack.dev/reference/methods/agents.sessions.setStatus/).
