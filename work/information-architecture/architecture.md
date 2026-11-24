# Stock Ontology information architecture

[Open the app-wide structure mockup](structure.html) to review the navigation, pages, and section ownership before designing individual screens.

[Open the clickable comparison](index.html). The comparison starts with the NVIDIA note from the screenshot. Use the top strip to switch concepts. The mockups use example data and simulate selected actions in memory.

## The problem

The NVIDIA screen presents the catalog title, catalog browse modes, a four-level breadcrumb, a dedicated return button, and the note title together. A reader has to distinguish the library’s browse state from the note’s identity. The breadcrumb and return button send them to the same vicinity. NVIDIA and the four analysts also appear on the screen, but those are related records and source metadata.

The same level mismatch appears elsewhere. Companies contains an Other Entities view. Search appears in the header, the rail, and two workflow menus, with a Notes entry that still uses the shared search route. The Ontology page presents a model guide, explorer controls, live record samples, registry definitions, and audit findings in one long page.

## Recommended structure

Use the **Dedicated reader** as the first release. Give users direct access to the existing directories and a stable reader for evidence deep links. Add contextual evidence sections to company, person, and theme records. Treat the **Research hubs** and **Research workspace** as two alternatives for where users do most of their reading.

| Level | Owns |
| --- | --- |
| Workflows and directories | Keep the Library’s Research, Notes, and Ontology tabs. Research owns Overview, Companies, Themes, and Other Entities. Notes owns the source library and reader. Ontology owns graph exploration and governance. |
| Global tools | Search, Paste a note, and Language in the shared shell. Ask Clippy remains available with current page context. Search filters include Notes scope. |
| Directories | Sorting, counts, alphabet filters, company or author groupings, and the currently selected group. |
| Research records | Company, person, theme, or note title and identity. Record-local sections cover events, views, relationships, source evidence, or extraction as appropriate. |
| Graph explorer | Model reference and instance records for entities, events, views, themes, and relationships. Subtype and registry status are explorer filters. |
| Governance | Published Registry and Audit. The Ontology rail gives researchers and operators direct links to Registry and Audit. Existing access rules govern who can see or use any action. |

### Navigation rules

1. Use the object’s title as the detail view’s only page heading. The library’s heading, description, grouping modes and counts belong to the list.
2. Give each detail view one visible parent route or a persistent list. Keep the title out of the breadcrumb when it is the page heading. Browser Back restores the actual browsing context. A direct link has a sensible default parent.
3. Store list context in the URL when relevant, including the selected company, author, alphabet, search filters, and sort if introduced. Notes reached from a search citation keep their source location and line anchor.
4. Put company and author links in record metadata. Company notes, authored notes, and search results all open the same note identity. Preserve any source-folder grouping used for unassigned or legacy notes and label it as such if exposed alongside graph-derived companies.
5. Give a note a **Source** view for reading and a separate **Extraction** view for the note’s processing state, entities, and relationships. Keep Process and correction actions within Extraction. Expose meaningful processing state in note metadata. If previous and next links are retained, show them only when the reader has an ordered list context.
6. Give Search its own explicit results page. A Notes link or quick action can preselect the Notes filter. Use Ask when a reader wants synthesis. The assistant can use the current record or query as context.
7. Give each event and view a clear link back to source evidence. Surface the company consensus on the company record and let the Views section expose the underlying views. A theme’s company exposure belongs to the theme, with links to affected company records.

## Page inventory and destinations

This covers the nine HTML routes in the current navigation registry and their variants, plus the Ask redirect and language utility. JSON endpoints support these experiences.

| Current page or state | Current responsibility | Proposed home |
| --- | --- | --- |
| `/` | Company and theme previews | Research Overview with entry points to directories and recent notes. |
| `/companies?kind=companies` | Company directory | Companies directory. |
| `/companies?kind=other` | People and other non-company entities, under Companies | Other Entities directory, with entity-type filters if needed. The workspace uses a result type. |
| `/entity/{id}`, company | Identity, consensus, themes, events, views, related entities | Company record. Overview owns identity and consensus. Events and Views are record sections. Connections contains linked themes and entities. Evidence notes provide source links. |
| `/entity/{id}`, person or other entity | Person or generic entity facts and linked items | Entity record. Profile owns its type and facets. Applicable events, views, and connections remain local. Authored research belongs to people and other attributable sources. |
| `/themes` | Theme directory | Themes directory. |
| `/theme/{id}` | Theme identity, exposure paths, mentions, events and views | Theme record. Exposure includes first- and second-order paths and distinguishes mentions from exposure. Events, Views and Evidence notes sit on the record. |
| `/catalog?view=company`, including `dir` and `alpha` | Company or folder groups and their note lists | Notes directory, with Company grouping and group or alphabet filters. Preserve general and unmatched folders. |
| `/catalog?view=author`, including `author`, `person` and `alpha` | Author groups and their note lists | Notes directory, with Author grouping and group or alphabet filters. Preserve the unassigned group. The person record links directly to authored research. |
| `/catalog?view=all` | All source notes | Notes directory, default All Notes view. |
| `/catalog?file=…`, contextual list variants, `format=raw#L…` | Note title and discovery controls, original text, extraction, processing, corrections and sibling links | Note record. Source and Extraction are local views. Rendered and plain text are Source display modes. Existing raw citations map to plain text with the original line anchor. |
| `/notes/new` | Paste title and content, save and process | New note as a global create action. Save opens the created note with its processing state. |
| `/search` and `/search?in=notes` | Best match, related records, events and views, note passages, advanced filters, and assistant | One Search experience with an optional Notes scope. Keep exact-match priority, passage citations and advanced filters. Ask opens with query context from results. |
| `/ontology?tab=entity/event/view/theme` | Model guide, samples, subtype and registry-status filters | Graph Explorer and its record-type views. Keep the model guide available via a disclosure or reference entry. |
| `/ontology?tab=edges` | Relationship schema, relationship samples, registry-status filters | Graph Explorer → Relationships. Relationship rows link to endpoints and source evidence. |
| `/ontology?tab=registry/audit` | Canonical definitions and data-quality findings | Governance → Registry or Audit. Link findings to affected records where available. |
| `/ask?context=…` and Clippy | Opens assistant through a redirect or shared dock | One persistent Ask action with record or query context. Legacy Ask URLs still resolve to the assistant. |
| `/set-language` | Sets locale and returns to the originating location | Language in the shared header, preserving the current route and state. |

## Three alternatives

| Concept | NVIDIA path | Best when | Tradeoff |
| --- | --- | --- | --- |
| **Dedicated reader** | Notes → By company → NVIDIA → note. The reader has one Notes return link that restores the NVIDIA list. | Notes are opened from several places and often read or shared on their own. | Comparing several notes takes more page changes. |
| **Research hubs** | Companies → NVIDIA → Evidence notes → note. The reader offers a company evidence breadcrumb and related sources. The Source library handles author browsing and cross-company notes. | Researchers usually start with a company or theme and read notes to validate its views. | People entering by author or citation need a reliable route through the Source library. A note may appear in several hubs, so its identity stays independent of the hub. |
| **Research workspace** | Workspace → Notes → select the NVIDIA note. The result list, reader and contextual links stay on one screen. | Analysts regularly jump between notes and related graph records during a review. | The layout uses more width and requires explicit selection and history behavior. The narrow layout stacks the panes. |

## Acceptance criteria for implementation

- Open one note from Company grouping, Author grouping, All Notes, a company or theme record, and Search. The same note identity opens each time. Browser Back and the visible parent control recover the expected list context.
- The NVIDIA reader exposes one heading, one parent control or list, and working links to the company and the four analysts. Source and Extraction have independent URLs or URL state.
- Existing note, entity, theme, catalog, search, and ontology links still resolve. Verify raw source links at a specific line.
- Check unassigned authors and folders, multiple company and author links, a missing source, empty lists, changed or unprocessed notes, and pending, failed, and completed jobs.
- Keep Process and corrections note-scoped. Verify that a change to one note preserves shared evidence supplied by other notes.
- Check keyboard navigation, one active section per navigation group, visible focus, mobile layout, and locale switching with query and source anchors intact.

The mockups cover navigation and representative screens. Search uses fixture matching, save and process are simulated, and graph corrections, real audit data, locale changes, and assistant responses require the app. This is a design handoff. The first implementation slice is extracting the note reader from the catalog shell while preserving list context and citation links.
