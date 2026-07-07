/**
 * AR Tools — Google Docs publish webhook (Apps Script).
 *
 * This is the script behind GOOGLE_APPS_SCRIPT_URL. The platform-api posts
 *   { folder_id, title, content, format, share }            (a Google Doc)
 *   { type: "sheet", folder_id, title, rows, share }         (a Google Sheet)
 * and expects back
 *   { success: true, doc_id, doc_url }                       (doc)
 *   { success: true, sheet_id, sheet_url }                   (sheet)
 *   (or { success: false, error }).
 *
 * `type` (added 2026-06): "doc" (default) builds a Google Doc; "sheet" builds a
 * Google Sheet from `rows` (an array of rows, each an array of cell strings).
 *
 * `share` (added 2026-06): how to share the new file —
 *   - "private" (default) → no sharing change (legacy behaviour).
 *   - "link"              → anyone with the link can VIEW.
 *   - "public"            → anyone on the internet can FIND + VIEW (search-
 *                           discoverable). Used by Content Syndication.
 * Sharing uses DriveApp.setSharing(...). The CONTENT SYNDICATION module needs
 * the Sheets capability + ANYONE sharing, so after grafting these in you must
 * REDEPLOY the Web App (Deploy → Manage deployments → edit → New version) and,
 * on first run, authorize the added Spreadsheet/Drive scopes.
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
 * IMAGE EMBEDDING (added 2026-07): the markdown renderer now inserts `![alt](url)`
 * image lines as real Doc images (used by the Maps report's "Local Rank Map").
 * This calls UrlFetchApp — after grafting it in you must REDEPLOY the Web App
 * (New version) and, on first run, authorize the added external-request scope.
 * Until then the Maps report still publishes; the image line just renders as
 * text (the map PNG is always saved regardless, and shows in the app + client PDF).
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
    var type = (req.type || 'doc').toLowerCase();
    var share = (req.share || 'private').toLowerCase();

    if (!folderId) {
      return _json({ success: false, error: 'missing_folder_id' });
    }

    if (type === 'sheet') {
      var sheetId = createSheetFromRows(folderId, title, req.rows || []);
      _applySharing(sheetId, share);
      return _json({
        success: true,
        sheet_id: sheetId,
        sheet_url: 'https://docs.google.com/spreadsheets/d/' + sheetId + '/edit',
      });
    }

    var content = req.content || '';
    var format = (req.format || 'markdown').toLowerCase();
    var docId = (format === 'html')
      ? createDocFromHtml(folderId, title, content)
      : createDocFromMarkdown(folderId, title, content);
    _applySharing(docId, share);

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
 * Apply a sharing mode to a newly-created file by id.
 *   "link"   → anyone with the link can view.
 *   "public" → anyone (incl. search) can find + view.
 *   anything else → leave private (default Drive behaviour).
 */
function _applySharing(fileId, share) {
  if (share !== 'link' && share !== 'public') { return; }
  var file = DriveApp.getFileById(fileId);
  var access = (share === 'public') ? DriveApp.Access.ANYONE : DriveApp.Access.ANYONE_WITH_LINK;
  file.setSharing(access, DriveApp.Permission.VIEW);
}

/**
 * Google Sheet from a 2-D array of strings. Writes the rows top-to-bottom into
 * the first sheet, then moves the new Spreadsheet out of My Drive root into the
 * client's folder (same move pattern as createDocFromMarkdown). Returns the id.
 */
function createSheetFromRows(folderId, title, rows) {
  var ss = SpreadsheetApp.create(title);
  var sheet = ss.getSheets()[0];
  if (rows && rows.length) {
    // Normalize to a rectangular range (Sheets requires equal-length rows).
    var width = 1;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || [];
      if (r.length > width) { width = r.length; }
    }
    var grid = [];
    for (var j = 0; j < rows.length; j++) {
      var row = rows[j] || [];
      var padded = [];
      for (var k = 0; k < width; k++) { padded.push(row[k] != null ? String(row[k]) : ''); }
      grid.push(padded);
    }
    sheet.getRange(1, 1, grid.length, width).setValues(grid);
  }
  SpreadsheetApp.flush();

  var file = DriveApp.getFileById(ss.getId());
  DriveApp.getFolderById(folderId).addFile(file);
  DriveApp.getRootFolder().removeFile(file);
  return ss.getId();
}

/**
 * HTML → Google Doc via Drive's native import. Drive converts the HTML into a
 * real Doc: <h2>/<h3> become heading styles, <strong> stays bold, <ul>/<ol>
 * become native lists, <a> become hyperlinks — exactly what WordPress's
 * "paste from Google Docs" importer reconstructs into blocks.
 */
function createDocFromHtml(folderId, title, html) {
  // Drive's HTML importer renders <p> blocks with no space-after (cramped) and
  // flattens <thead>/<th> into a plain row (header loses its bold/shading). Two
  // fixes, belt-and-suspenders because the importer applies styling
  // inconsistently: (1) a <style> block in <head> for paragraph spacing + table
  // borders, and (2) an inline transform that bolds + shades each <th> cell,
  // which survives import where element-level <style> alone sometimes doesn't.
  var styled = _styleForDocs(html);
  var head = '<head><meta charset="utf-8"><style>'
    + 'p{margin:0 0 10pt 0;line-height:1.5;}'
    + 'li{margin:0 0 4pt 0;}'
    + 'table{border-collapse:collapse;margin:0 0 12pt 0;}'
    + 'th,td{border:1px solid #cccccc;padding:6pt 9pt;text-align:left;vertical-align:top;}'
    + 'th{background-color:#f3f3f3;font-weight:bold;}'
    + '</style></head>';
  var wrapped = '<html>' + head + '<body>' + styled + '</body></html>';
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
 * Make table header cells survive Drive's HTML import. The importer drops the
 * <thead>/<th> distinction, so the header row reads like a data row. We bold +
 * shade each <th> inline and wrap its text in <strong> (text bold is the part
 * the importer most reliably keeps), so the header stays visually distinct in
 * the Doc. Idempotent enough for our generated HTML (bare <th> cells).
 */
function _styleForDocs(html) {
  return String(html).replace(/<th\b([^>]*)>([\s\S]*?)<\/th>/gi, function (match, attrs, inner) {
    var hasStyle = /\bstyle\s*=/.test(attrs);
    var styled = hasStyle
      ? attrs
      : attrs + ' style="background-color:#f3f3f3;font-weight:bold;text-align:left;"';
    return '<th' + styled + '><strong>' + inner + '</strong></th>';
  });
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

    // Image on its own line: ![alt](url). Used by the REPORTING modules (e.g. the
    // Maps "Local Rank Map"): fetch the URL and insert it as a real Doc image,
    // scaled down to the page content width. Falls back to the alt/URL text if the
    // fetch fails (image host down, private URL). Requires UrlFetchApp + image
    // scopes — authorized on first run after redeploy.
    var img = trimmed.match(/^!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)$/);
    if (img) {
      try {
        var blob = UrlFetchApp.fetch(img[2], { muteHttpExceptions: true }).getBlob();
        var imgEl = body.appendImage(blob);
        var w0 = imgEl.getWidth(), h0 = imgEl.getHeight();
        if (w0 > 468) {                       // ~6.5in content width on Letter
          imgEl.setWidth(468);
          imgEl.setHeight(Math.round(h0 * (468 / w0)));
        }
      } catch (imgErr) {
        body.appendParagraph(img[1] || img[2]);
      }
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
