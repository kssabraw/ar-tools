/**
 * AR Tools — Google Docs publish webhook (Apps Script).
 *
 * This is the script behind GOOGLE_APPS_SCRIPT_URL. The platform-api posts
 *   { folder_id, title, content, format }
 * and expects back
 *   { success: true, doc_id, doc_url }   (or { success: false, error }).
 *
 * `format` (added 2026-06):
 *   - "html"     → build the Doc with NATIVE Google Docs formatting (real
 *                  heading styles, bold, bullet/numbered lists, hyperlinks) by
 *                  importing HTML through Drive. Docs made this way copy-paste
 *                  cleanly into the WordPress block editor. Used by the CONTENT
 *                  modules: blog posts, service/location pages, Local SEO pages.
 *   - "markdown" → legacy behaviour, unchanged. Used by the REPORTING modules
 *                  (rank reports, Maps reports), which don't need WordPress
 *                  paste. Absent/unknown `format` also falls here, so older
 *                  callers keep working.
 *
 * SETUP (one-time): this script uses the advanced Drive service for the HTML
 * import. In the Apps Script editor: Services (+) → add "Drive API" (identifier
 * `Drive`, v2). Then redeploy the Web App (Deploy → Manage deployments → edit →
 * New version) so the live URL serves this version.
 *
 * NOTE: If you'd rather not replace your existing markdown rendering, you only
 * need to graft in the `format === 'html'` branch of doPost() plus
 * createDocFromHtml() below — the markdown path here is a reference
 * implementation and can be swapped for whatever you run today.
 */

function doPost(e) {
  try {
    var req = JSON.parse(e.postData.contents);
    var folderId = req.folder_id;
    var title = req.title || 'Untitled';
    var content = req.content || '';
    var format = (req.format || 'markdown').toLowerCase();

    if (!folderId) {
      return _json({ success: false, error: 'missing_folder_id' });
    }

    var docId = (format === 'html')
      ? createDocFromHtml(folderId, title, content)
      : createDocFromMarkdown(folderId, title, content);

    return _json({
      success: true,
      doc_id: docId,
      doc_url: 'https://docs.google.com/document/d/' + docId + '/edit',
    });
  } catch (err) {
    return _json({ success: false, error: String(err) });
  }
}

/**
 * HTML → Google Doc via Drive's native import. Drive converts the HTML into a
 * real Doc: <h2>/<h3> become heading styles, <strong> stays bold, <ul>/<ol>
 * become native lists, <a> become hyperlinks — exactly what WordPress's
 * "paste from Google Docs" importer reconstructs into blocks.
 */
function createDocFromHtml(folderId, title, html) {
  var wrapped = '<html><head><meta charset="utf-8"></head><body>' + html + '</body></html>';
  var blob = Utilities.newBlob(wrapped, 'text/html', title + '.html');
  var resource = {
    title: title,
    mimeType: 'application/vnd.google-apps.document',
    parents: [{ id: folderId }],
  };
  // `convert: true` performs the HTML → Google Doc conversion (advanced Drive
  // service, API v2). On a v3-only project use:
  //   Drive.Files.create({ name: title, mimeType: '...document', parents: [folderId] }, blob)
  var file = Drive.Files.insert(resource, blob, { convert: true });
  return file.id;
}

/**
 * Markdown → Google Doc (legacy / reports). Renders the constructs the
 * pipeline emits — ATX headings, unordered/ordered lists, blockquotes,
 * horizontal rules, and inline **bold** / [links](url) — as native Doc
 * formatting. Replace with your existing renderer if you prefer.
 */
function createDocFromMarkdown(folderId, title, markdown) {
  var doc = DocumentApp.create(title);
  var body = doc.getBody();
  body.clear();

  var lines = String(markdown).replace(/\r\n?/g, '\n').split('\n');
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].replace(/\s+$/, '');
    var trimmed = line.trim();
    if (!trimmed) { continue; }

    var h = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      var level = h[1].length;
      var p = body.appendParagraph('');
      var heads = [
        DocumentApp.ParagraphHeading.HEADING1,
        DocumentApp.ParagraphHeading.HEADING2,
        DocumentApp.ParagraphHeading.HEADING3,
        DocumentApp.ParagraphHeading.HEADING4,
        DocumentApp.ParagraphHeading.HEADING5,
        DocumentApp.ParagraphHeading.HEADING6,
      ];
      p.setHeading(heads[level - 1]);
      _appendInline(p, h[2].trim());
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      body.appendHorizontalRule();
      continue;
    }

    var ul = trimmed.match(/^[-*+]\s+(.*)$/);
    var ol = trimmed.match(/^\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      var item = body.appendListItem('');
      item.setGlyphType(ul ? DocumentApp.GlyphType.BULLET : DocumentApp.GlyphType.NUMBER);
      _appendInline(item, (ul ? ul[1] : ol[1]).trim());
      continue;
    }

    if (trimmed.charAt(0) === '>') {
      var q = body.appendParagraph('');
      q.setIndentStart(36);
      _appendInline(q, trimmed.replace(/^>\s?/, ''));
      continue;
    }

    var para = body.appendParagraph('');
    _appendInline(para, trimmed);
  }

  doc.saveAndClose();

  // Move the new Doc out of My Drive root into the client's folder.
  var file = DriveApp.getFileById(doc.getId());
  DriveApp.getFolderById(folderId).addFile(file);
  DriveApp.getRootFolder().removeFile(file);
  return doc.getId();
}

/**
 * Append inline markdown (**bold**, [text](url)) to a paragraph/list item as
 * real Doc runs (bold attribute, link URL) rather than literal characters.
 */
function _appendInline(el, text) {
  var token = /\*\*([^*]+)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  var last = 0, m;
  while ((m = token.exec(text)) !== null) {
    if (m.index > last) { el.appendText(text.substring(last, m.index)); }
    if (m[1] !== undefined) {
      el.appendText(m[1]).setBold(true);
      el.appendText('').setBold(false);
    } else {
      el.appendText(m[2]).setLinkUrl(m[3]);
      el.appendText('').setLinkUrl(null);
    }
    last = token.lastIndex;
  }
  if (last < text.length) { el.appendText(text.substring(last)); }
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
