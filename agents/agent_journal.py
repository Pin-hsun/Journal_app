"""
Journaling agent using CBT's emotion/cognition/behavior triangle.
"""

import os
import time
from datetime import datetime
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "..", "archived")

# Google Sheets configuration
GOOGLE_SHEETS_CREDENTIALS = os.path.join(os.path.dirname(__file__), "..", "credentials.json")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Journaling feedback")


def save_to_google_sheets(data):
    """Save feedback data to Google Sheets.

    Args:
        data: dict with keys 'timestamp' and 'feedback'

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("Please install gspread: pip install gspread google-auth")
        return False

    if not os.path.exists(GOOGLE_SHEETS_CREDENTIALS):
        print(f"Credentials file not found: {GOOGLE_SHEETS_CREDENTIALS}")
        return False

    try:
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        credentials = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS, scopes=scopes)
        client = gspread.authorize(credentials)

        # Open the spreadsheet (create if not exists)
        try:
            spreadsheet = client.open(GOOGLE_SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            spreadsheet = client.create(GOOGLE_SHEET_NAME)

        worksheet = spreadsheet.sheet1

        # Add headers if sheet is empty
        if worksheet.row_count == 0 or worksheet.cell(1, 1).value is None:
            headers = ['時間', '心得回饋']
            worksheet.append_row(headers)

        # Append the data row
        row = [
            data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            data.get('feedback', '')
        ]
        worksheet.append_row(row)
        return True

    except Exception as e:
        print(f"Error saving to Google Sheets: {e}")
        return False

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

MODELS = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-20250514",
}


def load_prompts():
    """Load prompts from journal_prompt.txt file."""
    prompt_file = os.path.join(os.path.dirname(__file__), "journal_prompt.txt")
    with open(prompt_file, "r") as f:
        content = f.read()

    # Parse the sections
    sections = {}
    current_section = None
    current_content = []

    for line in content.split("\n"):
        if line.startswith("[") and line.endswith("]"):
            if current_section:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[1:-1]
            current_content = []
        else:
            current_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


_prompts = load_prompts()
SYSTEM_PROMPT = _prompts["SYSTEM_PROMPT"]
REFRAME_PROMPT = _prompts["REFRAME_PROMPT"]
NARRATIVE_PROMPT = _prompts["NARRATIVE_PROMPT"]
SUMMARIZE_PROMPT = _prompts["SUMMARIZE_PROMPT"]
FEEDBACK_PROMPT = _prompts["FEEDBACK_PROMPT"]


def create_llm(model_name="opus"):
    """Create a ChatAnthropic LLM with the specified model."""
    model_id = MODELS.get(model_name.lower(), MODELS["opus"])
    return ChatAnthropic(
        model=model_id,
        temperature=0.7,
        max_tokens=1024,
        max_retries=5,
        api_key=ANTHROPIC_API_KEY
    )


def openai_2_langchain(messages):
    """Convert OpenAI message format to LangChain format."""
    lc_messages = []
    for msg in messages:
        if msg["role"] == "system":
            lc_messages.append(SystemMessage(content=msg["content"]))
        elif msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_messages.append(AIMessage(content=msg["content"]))
    return lc_messages


class JournalAgent:
    def __init__(self, model="opus"):
        self.llm = create_llm(model)
        self.model_name = model
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        self.last_metadata = None
        self.init_journal = None
        self.reframed_journal = None
        self.final_summary = None
        self.narrative_messages = []

    def generate_prompts(self):
        """Generate journaling prompt suggestions on demand."""
        prompt_request = [
            {"role": "system", "content": "用繁體中文產生 3-4 個不同的日記書寫靈感。保持簡短且親切。不要使用表情符號。"},
            {"role": "user", "content": "給我一些書寫靈感來幫助我開始。"},
        ]
        lc_messages = openai_2_langchain(prompt_request)
        response = self.llm.invoke(lc_messages)
        prompts = response.content
        self.messages.append({"role": "assistant", "content": prompts})
        return prompts

    def _save_to_archive(self, content, stage):
        """Save content to archived/ directory."""
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        filename = f"{stage}.txt"
        filepath = os.path.join(ARCHIVE_DIR, filename)
        with open(filepath, "w") as f:
            f.write(content)
        return filepath

    def cbt_receive(self, user_input):
        if self.init_journal is None:
            self.init_journal = user_input
        self.messages.append({"role": "user", "content": user_input})

    def cbt_reply(self):
        lc_messages = openai_2_langchain(self.messages)

        start_time = time.time()
        response = self.llm.invoke(lc_messages)
        elapsed_time = time.time() - start_time

        # Extract token usage from response metadata
        usage = response.response_metadata.get("usage", {})
        self.last_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "elapsed_time": elapsed_time,
            "model": self.model_name,
        }

        response_text = response.content
        self.messages.append({"role": "assistant", "content": response_text})
        return response_text

    def reframe(self):
        """Reframe the initial journal entry based on the conversation."""
        if not self.init_journal:
            return "沒有初始日記可以整理。"

        # Build conversation text (skip system prompt and first assistant greeting)
        conversation_lines = []
        for msg in self.messages[2:]:
            role = "You" if msg["role"] == "user" else "Agent"
            conversation_lines.append(f"{role}: {msg['content']}")
        conversation = "\n\n".join(conversation_lines)

        prompt = REFRAME_PROMPT.format(
            init_journal=self.init_journal,
            conversation=conversation
        )

        reframe_messages = [{"role": "user", "content": prompt}]
        lc_messages = openai_2_langchain(reframe_messages)

        start_time = time.time()
        response = self.llm.invoke(lc_messages)
        elapsed_time = time.time() - start_time

        usage = response.response_metadata.get("usage", {})
        self.last_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "elapsed_time": elapsed_time,
            "model": self.model_name,
        }

        reframed = response.content
        self.reframed_journal = reframed
        return reframed

    def start_narrative(self, reframed_journal=None):
        """Start the narrative therapy session with the reframed journal.

        Args:
            reframed_journal: Optional. If provided, use this instead of the one from reframe().
                              Useful for testing the narrative part directly.
        """
        if reframed_journal:
            self.reframed_journal = reframed_journal

        if not self.reframed_journal:
            return "沒有可用的整理日記。請先完成整理步驟或提供一份日記。"

        # Store the original reframed journal for use in feedback
        self.origin_reframed_journal = self.reframed_journal

        # Initialize narrative messages with the reframed journal as context
        system_content = f"{NARRATIVE_PROMPT}\n\n### Reframed Journal:\n{self.reframed_journal}"
        self.narrative_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "讓我們更深入地探索這個故事。"},
        ]

        # Get the first question from the LLM
        lc_messages = openai_2_langchain(self.narrative_messages)

        start_time = time.time()
        response = self.llm.invoke(lc_messages)
        elapsed_time = time.time() - start_time

        usage = response.response_metadata.get("usage", {})
        self.last_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "elapsed_time": elapsed_time,
            "model": self.model_name,
        }

        response_text = response.content
        self.narrative_messages.append({"role": "assistant", "content": response_text})
        return response_text

    def narrative_receive(self, user_input):
        """Receive user input during narrative therapy session."""
        self.narrative_messages.append({"role": "user", "content": user_input})

    def narrative_reply(self):
        """Generate a reply during narrative therapy session."""
        lc_messages = openai_2_langchain(self.narrative_messages)

        start_time = time.time()
        response = self.llm.invoke(lc_messages)
        elapsed_time = time.time() - start_time

        usage = response.response_metadata.get("usage", {})
        self.last_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "elapsed_time": elapsed_time,
            "model": self.model_name,
        }

        response_text = response.content
        self.narrative_messages.append({"role": "assistant", "content": response_text})
        return response_text

    def summarize(self):
        """Generate a reflection summary based on the narrative therapy conversation."""
        if not self.reframed_journal:
            return "沒有可用的整理日記。"

        # Build conversation text (skip system prompt and first user kickoff)
        conversation_lines = []
        for msg in self.narrative_messages[2:]:
            role = "You" if msg["role"] == "user" else "Agent"
            conversation_lines.append(f"{role}: {msg['content']}")
        conversation = "\n\n".join(conversation_lines)

        prompt = SUMMARIZE_PROMPT.format(
            reframed_journal=self.reframed_journal,
            conversation=conversation
        )

        summarize_messages = [{"role": "user", "content": prompt}]
        lc_messages = openai_2_langchain(summarize_messages)

        start_time = time.time()
        response = self.llm.invoke(lc_messages)
        elapsed_time = time.time() - start_time

        usage = response.response_metadata.get("usage", {})
        self.last_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "elapsed_time": elapsed_time,
            "model": self.model_name,
        }

        summary = response.content
        self.final_summary = summary
        return summary

    def finalize(self, title):
        """Start the finalize phase - ask about current emotion."""
        if not hasattr(self, 'final_summary') or not self.final_summary:
            return "沒有可用的摘要來完成。"

        self.journal_title = title
        origin_story = getattr(self, 'origin_reframed_journal', self.reframed_journal) or ""

        system_content = FEEDBACK_PROMPT.format(
            title=title,
            origin_story=origin_story,
            summary=self.final_summary
        )
        self.finalize_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"我把日記取名為「{title}」。"},
        ]

        lc_messages = openai_2_langchain(self.finalize_messages)

        start_time = time.time()
        response = self.llm.invoke(lc_messages)
        elapsed_time = time.time() - start_time

        usage = response.response_metadata.get("usage", {})
        self.last_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "elapsed_time": elapsed_time,
            "model": self.model_name,
        }

        response_text = response.content
        self.finalize_messages.append({"role": "assistant", "content": response_text})
        return response_text

    def finalize_receive(self, user_input):
        """Receive user input during finalize phase."""
        self.finalize_messages.append({"role": "user", "content": user_input})

    def finalize_reply(self):
        """Generate reply during finalize phase (emotion reflection)."""
        lc_messages = openai_2_langchain(self.finalize_messages)

        start_time = time.time()
        response = self.llm.invoke(lc_messages)
        elapsed_time = time.time() - start_time

        usage = response.response_metadata.get("usage", {})
        self.last_metadata = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "elapsed_time": elapsed_time,
            "model": self.model_name,
        }

        response_text = response.content
        self.finalize_messages.append({"role": "assistant", "content": response_text})
        return response_text

    @property
    def feedback_complete(self):
        """Check if feedback conversation is complete (after 2 user exchanges)."""
        # finalize_messages: system, user(title), assistant, user, assistant, user, assistant = 7
        return hasattr(self, 'finalize_messages') and len(self.finalize_messages) >= 7

    def save_feedback(self, user_feedback):
        """Save user feedback to Google Sheets.

        Args:
            user_feedback: User's feedback text

        Returns:
            bool: True if successful, False otherwise
        """
        data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'feedback': user_feedback
        }
        return save_to_google_sheets(data)
