import unittest
from types import SimpleNamespace

from storage.registry import ProviderRegistry


class ProviderRegistryTests(unittest.TestCase):
    def test_register_and_create_provider(self):
        registry = ProviderRegistry()

        sentinel = object()
        registry.register("dummy", lambda name, config, remote: sentinel)

        config = SimpleNamespace(
            get_remote=lambda name: SimpleNamespace(type="dummy")
        )

        self.assertIs(registry.create("example", config), sentinel)
        self.assertEqual(registry.supported_types(), ("dummy",))

    def test_unknown_provider_has_actionable_error(self):
        registry = ProviderRegistry()
        with self.assertRaisesRegex(ValueError, "unknown"):
            registry.get("unknown")


if __name__ == "__main__":
    unittest.main()
