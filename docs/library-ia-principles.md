# Stock Research Library information architecture principles

Change where users find an existing capability while preserving what it does. Start with an inventory of the live app. For each page and view, record the paths users take to reach it, the data and actions it exposes, and the URLs or citations people may have saved. Use that inventory to check that the proposed structure preserves the same workflows.

## Give each control a home

- **Global navigation** connects the main areas of the Library. Treat an existing view as part of its current workflow unless there is an explicit decision to give it a separate destination. For example, the Other Entities view belongs to Companies in the existing app.
- **Shared tools** serve several areas. Search and the research assistant can have a common entry point while carrying the current page or query as context. A search entry point and a search filter perform different jobs. Changing where Search is opened should preserve its existing results and URL behavior.
- **List views** own browsing controls such as grouping by company or author, filters, sort order, and counts. Users should be able to return to the same list state after opening an item.
- **Detail views** lead with the record itself. Put the title first, show company and author links as metadata, and place actions with the material they affect. A single contextual return link is enough when a breadcrumb and a Back button would lead to the same place.

## Keep evidence connected

A note has one identity whether someone reaches it from a company, an author, a theme, or Search. Keep existing citation URLs and line anchors usable. Preserve the reader’s return context and provide a predictable parent for direct links. Keep processing state visible where readers need it, and verify that processing and correction actions remain reachable and behave as before.

## Review the structure before designing pages

Use a full app map and simple wireframes to agree on destinations, page sections, and the paths between them. Mark any proposed addition, removal, or behavior change separately for review. Compare the map to the current app before using it to guide implementation. Style decisions can follow the structure. Classic and Modern can express the same structure differently through CSS while preserving access to the same content and actions.

Verify the implementation by walking existing workflows before and after the change. Include bookmarked URLs, search results and filters, Note Source and extraction actions, citation anchors, and return navigation. Visual review checks the new hierarchy. Workflow parity checks that the Library still works as expected.
