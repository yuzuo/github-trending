import unittest
import httpx

from app.translation import Translator, TranslationError, split_markdown


class TranslationTests(unittest.TestCase):
    def test_chunks_preserve_every_character(self):
        original = '# Title\n\n' + 'long sentence. ' * 2000 + '\n\n```python\nprint(1)\n```\n'
        pieces = split_markdown(original, limit=1000)
        self.assertEqual(''.join(pieces), original)
        self.assertTrue(all(len(piece) <= 1000 for piece in pieces))

    def test_protected_code_and_link_survive_translation(self):
        original = '# Hello\n\n[docs](https://example.com/a?q=1)\n\n```sh\necho hi\n```\n'
        def respond(request):
            import json
            body = json.loads(request.content)
            content = body['messages'][-1]['content'].replace('Hello', '你好').replace('docs', '文档')
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            translated = Translator(client, 'https://translate.test/v1', 'model', 'secret').translate(original)
        self.assertIn('# 你好', translated)
        self.assertIn('https://example.com/a?q=1', translated)
        self.assertIn('```sh\necho hi\n```', translated)

    def test_truncated_completion_is_failure(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': 'half'}}]}))) as client:
            with self.assertRaises(TranslationError):
                Translator(client, 'https://translate.test/v1', 'model', 'secret').translate('hello')

    def test_provider_body_is_not_exposed(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text='secret'))) as client:
            with self.assertRaises(TranslationError) as raised:
                Translator(client, 'https://translate.test/v1', 'model', 'secret').translate('hello')
            self.assertNotIn('secret', str(raised.exception))

    def test_missing_protected_token_is_failure(self):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '你好'}}]}))) as client:
            with self.assertRaises(TranslationError):
                Translator(client, 'https://translate.test/v1', 'model', 'secret').translate('hello `code`')

    def test_indented_and_longer_fenced_code_are_untouched(self):
        import json
        def respond(request):
            content = json.loads(request.content)['messages'][-1]['content'].replace('echo hello', 'altered')
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
        for original in ['    echo hello\n', '```sh\necho hello\n````\n', '> ```sh\n> echo hello\n> ```\n', '```sh\necho hello']:
            with self.subTest(original=original), httpx.Client(transport=httpx.MockTransport(respond)) as client:
                self.assertEqual(Translator(client, 'https://translate.test/v1', 'model', 'secret').translate(original), original)

    def test_chunk_limit_at_newline_boundary(self):
        chunks = split_markdown('a' * 1000 + '\n' + 'b' * 1000, limit=1000)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))

    def test_unclosed_quoted_fence_does_not_hide_following_prose(self):
        import json
        original = '> ```sh\n> echo hello\n\n# Installation\n\nRun the installer.\n'
        def respond(request):
            content = json.loads(request.content)['messages'][-1]['content'].replace('Installation', '安装').replace('echo hello', 'altered')
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            result = Translator(client, 'https://translate.test/v1', 'model', 'secret').translate(original)
            self.assertIn('# 安装', result)
            self.assertIn('echo hello', result)


if __name__ == '__main__':
    unittest.main()
