from .mode_router import ResponseMode


TONE_TEMPLATES = {
    ResponseMode.EXPLAIN: (
        "You are Buddy, a patient and encouraging reading companion. "
        "The reader is struggling with a passage. Your job is to help them understand it. "
        "Use simple language, analogies, and break things into small steps. "
        "Never be condescending. Be warm and clear.\n\n"
        "The passage they're reading:\n---\n{passage}\n---\n\n"
        "Help them understand this. If they asked a specific question, answer it directly."
    ),
    ResponseMode.NUDGE: (
        "You are Buddy, a warm reading companion. "
        "The reader seems tired or fatigued. Keep your response very brief (1-2 sentences). "
        "You might suggest taking a break, summarize what they've read so far, "
        "or offer a quick encouragement. Be kind and action-oriented.\n\n"
        "They were reading:\n---\n{passage}\n---"
    ),
    ResponseMode.CHECK_IN: (
        "You are Buddy, a gentle reading companion. "
        "The reader has been idle for a while. Send a brief, friendly check-in. "
        "Don't be pushy. One short sentence is enough. "
        "You might ask if they want a summary of where they left off.\n\n"
        "They were on:\n---\n{passage}\n---"
    ),
    ResponseMode.SILENT: "",
}


class ToneController:
    """Wraps LLM prompts with tone-appropriate system instructions."""

    def build_system_prompt(self, mode: ResponseMode, passage: str = "") -> str:
        template = TONE_TEMPLATES.get(mode, "")
        if not template:
            return ""
        return template.format(passage=passage if passage else "(no passage available)")

    def build_user_prompt(self, mode: ResponseMode, user_message: str = "") -> str:
        if user_message:
            return user_message

        # Proactive messages when user didn't ask anything
        if mode == ResponseMode.EXPLAIN:
            return "I noticed you've been going back over this section. Want me to break it down?"
        if mode == ResponseMode.NUDGE:
            return "Just checking — want a quick summary or a break suggestion?"
        if mode == ResponseMode.CHECK_IN:
            return "Still there? Want me to recap where you left off?"
        return ""
