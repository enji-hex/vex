from pathlib import Path
import subprocess
import os, sys
import ast, inspect
from langchain_core.tools import BaseTool, tool

# 
# move to MCP
# 

@tool
def bandcamp_dl(url: str):
    """
    Download music albums or tracks from Bandcamp.
    Use this tool for downloading ANY albums or tracks when the URL includes bandcamp.com.
    """
    try:
        res = subprocess.run(["bandcamp_dl", url], capture_output=True, text=True)
        print(res.returncode)

        if res.returncode == 0:
            return f"Successfully downloaded Bandcamp release from {url}"
        else:
            return f"Download failed with error: {res.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Download time out after 4 minutes"
    except Exception as e:
        return "System errro execute bandcamp_dl"


def web_request(url: str) -> str:
    """
    Raw web request could be rejected by antibot protection, try it as 1st option for website data extraction
    """
    from curl_cffi import Session
    import html_text

    if "http" not in url:
        return f"Provided url is invalid link"
    session = Session(impersonate="firefox147")
    resp = session.get(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        },
    )

    if resp.status_code != 200:
        return f"Error:fetch {url} response {resp.status_code}"

    result = []
    for line in html_text.extract_text(resp.text).strip().split("\n"):
        if len(line) > 30:
            result.append(line)
    return f"SOURCE:{url}\n" + " ".join(result)


@tool
def duckduckgo_search(query: str) -> str:
    """Search DuckDuckGo for live web information."""
    import curl_cffi
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs

    session = curl_cffi.Session()
    clean_q = query.strip("'\"")
    resp = session.post(
        "https://html.duckduckgo.com/html/",
        data={"q": clean_q},
        impersonate="firefox144",
        timeout=10,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        },
    )
    if resp.status_code != 200:
        return f"Error: DuckDuckGo returned status {resp.status_code}"

    soup = BeautifulSoup(resp.text, "html.parser")
    raw_links = [str(i.get("href")) for i in soup.select(".result__a")]

    fetched_pages = []
    visited = 0
    for raw_href in raw_links:
        if visited >= 3:  # Limit to top 3 to keep response fast and clean
            break

        # Unwrap DDG redirect URL (/l/?uddg=https%3A%2F%2F...)
        parsed = urlparse(raw_href)
        qs = parse_qs(parsed.query)

        if "uddg" in qs:
            target_url = qs["uddg"][0]
        elif raw_href.startswith("http"):
            target_url = raw_href
        else:
            continue

        try:
            # Fetch content using web_request
            page_text = web_request(target_url)[:3000]
            fetched_pages.append(f"{page_text}")
            visited += 1
        except Exception:
            pass

    if not fetched_pages:
        return f"DUCKDUCKGO: No links could be fetched for query '{clean_q}'."

    return (
        f"=== DUCKDUCKGO FETCHED RESULTS FOR '{clean_q}' ===\n\n"
        + "\n\n---\n\n".join(fetched_pages)
    )


tools = [
    obj
    for _, obj in inspect.getmembers(sys.modules[__name__])
    if isinstance(obj, BaseTool)
]
print(f"Loaded {len(tools)} tools:", [t.name for t in tools])
tools_by_name = {tool.name: tool for tool in tools}
