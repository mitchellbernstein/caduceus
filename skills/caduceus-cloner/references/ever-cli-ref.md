# Ever CLI Reference

Ever CLI controls a headless browser for product inspection. Agents use this during
the Inspect and QA phases to navigate, interact with, and screenshot web products.

## Session Management

```bash
ever start --url <url>            # Start browser session at URL
ever start --url <url> --browser chromium  # Specify browser
ever stop                         # Stop session (always do when done)
ever status                       # Check if session is running
```

**IMPORTANT**: Always `ever stop` when done. Sessions persist until stopped.
Use `trap 'ever stop' EXIT` in shell scripts.

## Navigation

```bash
ever navigate <url>               # Navigate to a new URL in session
ever back                        # Go back in history
ever forward                     # Go forward in history
ever refresh                     # Refresh current page
```

## Reading the Page

```bash
ever snapshot                    # Get accessibility tree (interactive elements)
ever snapshot --full            # Full page content, not just interactive
ever extract                     # Extract all text content as markdown
ever title                       # Get page title
ever url                         # Get current URL
```

## Taking Screenshots

```bash
ever screenshot                                    # Screenshot current viewport
ever screenshot --output screenshots/test.jpg      # Save to file
ever screenshot --full-page                       # Full page scroll capture
ever screenshot --output screenshots/test.jpg --full-page
```

## Interacting with Elements

First run `ever snapshot` to get element refs (`@e1`, `@e2`, etc.), then:

```bash
ever click <ref>              # Click element (e.g., ever click @e5)
ever double-click <ref>      # Double-click element
ever right-click <ref>       # Right-click (context menu)
ever hover <ref>             # Hover over element

ever input <ref> <text>       # Type text into input field
ever input <ref> ""          # Clear input field
ever select <ref> <option>   # Select option in dropdown

ever check <ref>             # Check a checkbox
ever uncheck <ref>           # Uncheck a checkbox
```

## Waiting and Async

```bash
ever wait <seconds>          # Wait for specified seconds
ever wait-for <selector>     # Wait for element matching CSS selector
ever wait-for-url <pattern>  # Wait for URL matching regex pattern
```

## Debugging

```bash
ever console                  # Get browser console logs (JS errors, console.log)
ever network                  # Show network request log
ever cookies                  # Get all cookies
ever clear-cookies           # Clear cookies
```

## Tips

- Always `ever snapshot` first to see what elements are available
- Element refs (`@e1`, `@e2`) are stable for one page load — re-snapshot after navigation
- Use `ever screenshot --full-page` for complex pages with scroll
- `ever extract` is faster than `ever snapshot` for reading text content
- For authenticated pages, ensure session cookies are set before inspecting
