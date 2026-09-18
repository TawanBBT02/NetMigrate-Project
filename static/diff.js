/*
 * Two-column aligned diff view (docs/web-layer-spec.md section 4.1).
 *
 * Rows pair a source line with the output line(s) it produced. Alignment is
 * driven by `source_line` on each output line, not by naive line-number
 * zipping -- a structural rule (OSPF area promotion, VLAN batch expansion)
 * can turn one source line into several output lines, or several source
 * lines into one, so a 1:1 row-per-index pairing would drift out of sync
 * almost immediately.
 *
 * Every provenance also gets a non-colour signal (border style + a text
 * badge, never colour alone) per spec: "colour must not be the only signal,
 * since the report may be printed in greyscale." All text is inserted with
 * textContent, never innerHTML, so configuration text is never parsed as
 * markup (spec section 5).
 */

const NetMigrateDiff = (() => {
  const PROVENANCE_INFO = {
    RULE: {
      label: 'Rule-based',
      badge: null,
      rowClass: 'nm-diff-rule',
    },
    AI: {
      label: 'AI suggestion',
      badge: 'AI',
      rowClass: 'nm-diff-ai',
    },
    UNMAPPED: {
      label: 'Unmapped',
      badge: 'UNMAPPED',
      rowClass: 'nm-diff-unmapped',
    },
    GENERATED: {
      label: 'Generated',
      badge: null,
      rowClass: 'nm-diff-generated',
    },
  };

  let stylesInjected = false;

  // Injected once per page rather than living in templates/index.html, so
  // any page can drop in a <div> and call NetMigrateDiff.render() on it.
  function injectStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    const style = document.createElement('style');
    style.id = 'nm-diff-styles';
    style.textContent = `
      .nm-diff-table { border-collapse: collapse; width: 100%; font-size: 0.8125rem; }
      .nm-diff-table td { vertical-align: top; padding: 1px 8px; }
      .nm-diff-lineno {
        width: 1%; white-space: nowrap; text-align: right;
        color: #9ca3af; user-select: none;
      }
      .nm-diff-src-text, .nm-diff-out-text {
        white-space: pre-wrap; word-break: break-word;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        border-left: 3px solid transparent;
      }
      .nm-diff-src-text { padding-left: 8px; }
      .nm-diff-out-text { padding-left: 8px; }
      .nm-diff-table tr.nm-diff-empty > td { color: transparent; }

      /* Provenance treatments: colour PLUS a distinct border style, so the
         encoding survives greyscale printing. */
      .nm-diff-rule .nm-diff-out-text {
        border-left-style: solid;
        border-left-color: #9ca3af; /* neutral, "normal" per spec */
      }
      .nm-diff-ai .nm-diff-out-text {
        background: rgba(217, 119, 6, 0.12);
        border-left-style: dashed;
        border-left-color: #d97706;
      }
      .nm-diff-unmapped .nm-diff-out-text {
        background: rgba(220, 38, 38, 0.12);
        border-left-style: double;
        border-left-width: 5px;
        border-left-color: #dc2626;
      }
      .nm-diff-generated .nm-diff-out-text {
        border-left-style: dotted;
        border-left-color: #d1d5db;
        color: #9ca3af;
        font-style: italic;
      }
      :root.dark .nm-diff-lineno { color: #6b7280; }
      :root.dark .nm-diff-rule .nm-diff-out-text { border-left-color: #6b7280; }
      :root.dark .nm-diff-ai .nm-diff-out-text { background: rgba(217, 119, 6, 0.22); }
      :root.dark .nm-diff-unmapped .nm-diff-out-text { background: rgba(220, 38, 38, 0.22); }
      :root.dark .nm-diff-generated .nm-diff-out-text { color: #6b7280; }

      .nm-diff-badge {
        display: inline-block; font-size: 0.625rem; font-weight: 700;
        letter-spacing: 0.03em; text-transform: uppercase;
        padding: 0 4px; border-radius: 3px; margin-right: 6px;
        border: 1px solid currentColor;
      }
      .nm-diff-ai .nm-diff-badge { color: #b45309; }
      .nm-diff-unmapped .nm-diff-badge { color: #b91c1c; }

      .nm-diff-review-mark {
        display: inline-block; margin-right: 4px; cursor: help;
      }

      .nm-diff-legend {
        display: flex; flex-wrap: wrap; gap: 12px 20px;
        font-size: 0.75rem; margin-bottom: 10px;
        padding: 8px 10px; border: 1px solid #e5e7eb; border-radius: 6px;
      }
      :root.dark .nm-diff-legend { border-color: #374151; }
      .nm-diff-legend-item { display: flex; align-items: center; gap: 6px; }
      .nm-diff-swatch {
        display: inline-block; width: 22px; height: 12px; border-left-width: 4px;
      }
      .nm-diff-legend .nm-diff-rule-swatch { border-left: 3px solid #9ca3af; }
      .nm-diff-legend .nm-diff-ai-swatch {
        border-left: 4px dashed #d97706; background: rgba(217, 119, 6, 0.12);
      }
      .nm-diff-legend .nm-diff-unmapped-swatch {
        border-left: 5px double #dc2626; background: rgba(220, 38, 38, 0.12);
      }
      .nm-diff-legend .nm-diff-generated-swatch {
        border-left: 3px dotted #d1d5db;
      }
    `;
    document.head.appendChild(style);
  }

  function buildLegend() {
    const legend = document.createElement('div');
    legend.className = 'nm-diff-legend';
    legend.setAttribute('role', 'note');
    legend.setAttribute('aria-label', 'Diff colour legend');

    const items = [
      { swatch: 'nm-diff-rule-swatch', text: 'Rule-based (solid border)' },
      { swatch: 'nm-diff-ai-swatch', text: 'AI [AI] (dashed border, badge)' },
      { swatch: 'nm-diff-unmapped-swatch', text: 'Unmapped [UNMAPPED] (double border, badge)' },
      { swatch: 'nm-diff-generated-swatch', text: 'Generated (dotted border, muted)' },
      { swatch: null, text: '⚠ needs review (marker, independent of colour)' },
    ];

    for (const item of items) {
      const el = document.createElement('span');
      el.className = 'nm-diff-legend-item';
      if (item.swatch) {
        const swatch = document.createElement('span');
        swatch.className = `nm-diff-swatch ${item.swatch}`;
        el.appendChild(swatch);
      } else {
        const mark = document.createElement('span');
        mark.textContent = '⚠';
        el.appendChild(mark);
      }
      const label = document.createElement('span');
      label.textContent = item.text;
      el.appendChild(label);
      legend.appendChild(el);
    }
    return legend;
  }

  // Pairs source lines with the output line(s) each produced, in output
  // order. Source lines no output line claims (fully absorbed into a
  // structural group, or simply not referenced) still get their own
  // source-only row, in increasing line-number order, so nothing from the
  // source disappears from the view.
  function buildRows(sourceText, lines) {
    const srcLines = sourceText.length ? sourceText.split('\n') : [];
    const rows = [];
    const usedSrc = new Set();
    let srcPointer = 1;

    for (const line of lines) {
      const sl = line.source_line;
      if (sl == null) {
        rows.push({ source: null, outputs: [line] });
        continue;
      }
      while (srcPointer < sl) {
        if (!usedSrc.has(srcPointer) && srcPointer - 1 < srcLines.length) {
          rows.push({ source: srcPointer, outputs: [] });
        }
        srcPointer++;
      }
      if (sl >= srcPointer) srcPointer = sl + 1;

      const last = rows[rows.length - 1];
      if (last && last.source === sl) {
        last.outputs.push(line);
      } else {
        rows.push({ source: sl, outputs: [line] });
        usedSrc.add(sl);
      }
    }

    while (srcPointer - 1 < srcLines.length) {
      if (!usedSrc.has(srcPointer)) {
        rows.push({ source: srcPointer, outputs: [] });
      }
      srcPointer++;
    }

    return { rows, srcLines };
  }

  function outputCell(line) {
    const info = PROVENANCE_INFO[line.provenance] || PROVENANCE_INFO.RULE;
    const cell = document.createElement('td');
    cell.className = 'nm-diff-out-text';

    if (line.needs_review) {
      const mark = document.createElement('span');
      mark.className = 'nm-diff-review-mark';
      mark.textContent = '⚠';
      mark.title = 'Needs review';
      cell.appendChild(mark);
    }
    if (info.badge) {
      const badge = document.createElement('span');
      badge.className = 'nm-diff-badge';
      badge.textContent = info.badge;
      cell.appendChild(badge);
    }

    const text = document.createElement('span');
    text.textContent = line.text; // textContent only -- never innerHTML
    cell.appendChild(text);

    const titleParts = [`provenance: ${line.provenance}`];
    titleParts.push(`rule_id: ${line.rule_id == null ? '(none)' : line.rule_id}`);
    titleParts.push(`source_line: ${line.source_line == null ? '(none)' : line.source_line}`);
    if (line.needs_review) titleParts.push('needs review');
    cell.title = titleParts.join('\n');

    return cell;
  }

  function textCell(className, text) {
    const cell = document.createElement('td');
    cell.className = className;
    cell.textContent = text == null ? '' : text;
    return cell;
  }

  function linenoCell(n) {
    const cell = document.createElement('td');
    cell.className = 'nm-diff-lineno';
    cell.textContent = n == null ? '' : String(n);
    return cell;
  }

  // container: a DOM element. result: the /api/convert response payload
  // (must have source_text and lines, per CLAUDE.md section 4's contract).
  function render(container, result) {
    injectStyles();
    container.textContent = '';
    container.appendChild(buildLegend());

    const wrapper = document.createElement('div');
    wrapper.className = 'overflow-x-auto border border-gray-200 dark:border-gray-700 rounded';
    const table = document.createElement('table');
    table.className = 'nm-diff-table';

    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    headRow.className = 'text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700';
    ['#', 'Source', '#', 'Output'].forEach((label) => {
      const th = document.createElement('th');
      th.className = 'py-1 px-2 font-medium';
      th.textContent = label;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    const { rows, srcLines } = buildRows(result.source_text || '', result.lines || []);

    let outputLineNo = 0;
    for (const row of rows) {
      const outputs = row.outputs.length ? row.outputs : [null];
      outputs.forEach((line, i) => {
        const tr = document.createElement('tr');
        if (line) {
          const info = PROVENANCE_INFO[line.provenance] || PROVENANCE_INFO.RULE;
          tr.className = info.rowClass;
        } else {
          tr.className = 'nm-diff-empty';
        }

        if (i === 0) {
          if (row.source != null) {
            tr.appendChild(linenoCell(row.source));
            tr.appendChild(textCell('nm-diff-src-text', srcLines[row.source - 1]));
          } else {
            tr.appendChild(linenoCell(null));
            tr.appendChild(textCell('nm-diff-src-text', ''));
          }
        } else {
          tr.appendChild(linenoCell(null));
          tr.appendChild(textCell('nm-diff-src-text', ''));
        }

        if (line) {
          outputLineNo++;
          tr.appendChild(linenoCell(outputLineNo));
          tr.appendChild(outputCell(line));
        } else {
          tr.appendChild(linenoCell(null));
          tr.appendChild(textCell('nm-diff-out-text', ''));
        }

        tbody.appendChild(tr);
      });
    }

    table.appendChild(tbody);
    wrapper.appendChild(table);
    container.appendChild(wrapper);
  }

  return { render };
})();
