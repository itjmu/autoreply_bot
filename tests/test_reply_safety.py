import unittest
from reply_safety import sanitize_reply


class ReplySafetyTests(unittest.TestCase):
    def test_language_analysis_is_rejected_entirely(self):
        sample = """The user sent a message in what appears to be a constructed or distorted language: "Valekum salom meshava szo shmo sozen nagzen". I need to identify the language and respond appropriately according to the instructions.

First, let's analyze the message. It looks like a greeting, possibly inspired by Arabic or Persian, but with unusual spellings.

Given the context, the user might be speaking Tajik (the owner's native language) or another language.

The main instructions block says: "If in MAIN INSTRUCTIONS directly specified language — answer in it."

The priority list:
1. If in MAIN INSTRUCTIONS directly specified language — answer in it.
2. Otherwise — in the native/main language of the owner: Tajik.
3. Allowed languages: Russian, English.

Since there's no direct language specification in the main instructions, I should use Tajik, the owner's native language."""
        self.assertEqual(sanitize_reply(sample), "")
        self.assertEqual(sanitize_reply(sample + "\nFinal answer: Hello!"), "")

    def test_normal_replies_and_tagged_final_answer(self):
        for text in [
            "I need your order number.",
            "Could you rephrase?",
            "Ва алейкум салом! Шумо чӣ хелед?",
        ]:
            self.assertEqual(sanitize_reply(text), text)
        self.assertEqual(sanitize_reply("<think>private</think>Hello!"), "Hello!")
        self.assertEqual(sanitize_reply("<analysis>unfinished"), "")
        self.assertEqual(sanitize_reply("Hello!<analysis>unfinished"), "Hello!")
