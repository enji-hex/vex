class Encoding:
    def __init__(self, name: str = "cl100k_base"):
        self.name = name

    def encode(self, text: str, **kwargs) -> list[int]:
        # Approximate tokenization using byte indices
        return list(text.encode("utf-8"))

    def decode(self, tokens: list[int], **kwargs) -> str:
        return bytes(tokens).decode("utf-8", errors="ignore")


def get_encoding(encoding_name: str) -> Encoding:
    return Encoding(encoding_name)


def encoding_for_model(model_name: str) -> Encoding:
    return Encoding(model_name)