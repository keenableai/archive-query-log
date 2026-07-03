from uuid import UUID, uuid4

from pydantic import HttpUrl

from archive_query_log.config import Config
from archive_query_log.orm import Archive, Provider
from archive_query_log.utils.time import utc_now

PROVIDERS = [
    ("google", UUID("f205fc44-d918-4b79-9a7f-c1373a6ff9f2"), ["google.com"], ["/search?"], 10.0),
    ("bing", UUID("a0d3e9d1-6b95-46a4-b4d7-3f00de99ae7d"), ["bing.com"], ["/search?"], 9.0),
    ("duckduckgo", UUID("3725fae7-edf7-4243-bcce-e5ccb615ae76"), ["duckduckgo.com", "html.duckduckgo.com"], ["/?", "/html/?"], 8.0),
    ("yahoo", UUID("6c8f6e76-13e9-436b-8ea3-1645bce0032c"), ["search.yahoo.com"], ["/search"], 7.0),
    ("ecosia", UUID("7a88141f-90b9-49a5-9083-9a922038c16c"), ["ecosia.org"], ["/search?"], 6.0),
    ("brave", UUID("e3be3140-7f78-4de1-a43b-6c75d345e4c4"), ["search.brave.com"], ["/search?"], 5.0),
    ("mojeek", UUID("74ee3c4a-1cb5-4d0f-928e-f42f8c0200a4"), ["mojeek.com"], ["/search?"], 4.0),
    ("ask", UUID("24fb5290-44aa-40e4-8272-0126a74d86cd"), ["ask.com"], ["/web?"], 3.0),
    ("qwant", UUID("66e6df7a-eb63-4d0d-ad42-9a1a2f778cfe"), ["qwant.com"], ["/?"], 2.0),
]


def main() -> None:
    config = Config()
    actions = []

    archive = Archive(
        index=config.es.index_archives,
        id=uuid4(),
        name="Wayback Machine",
        cdx_api_url=HttpUrl("https://web.archive.org/cdx/search/cdx"),
        memento_api_url=HttpUrl("https://web.archive.org/web"),
        priority=1.0,
        last_modified=utc_now(),
    )
    actions.append(archive.create_action())

    for name, provider_id, domains, prefixes, priority in PROVIDERS:
        provider = Provider(
            index=config.es.index_providers,
            id=provider_id,
            name=name,
            domains=domains,
            url_path_prefixes=prefixes,
            priority=priority,
            last_modified=utc_now(),
        )
        actions.append(provider.create_action())

    config.es.bulk(actions)
    config.es.client.indices.refresh(index=",".join([config.es.index_archives, config.es.index_providers]))
    print("archives:", config.es.client.count(index=config.es.index_archives)["count"])
    print("providers:", config.es.client.count(index=config.es.index_providers)["count"])


if __name__ == "__main__":
    main()
