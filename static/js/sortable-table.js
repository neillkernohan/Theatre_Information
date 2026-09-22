// Click-to-sort for any <table class="sortable">.
//
// Click a header to sort ascending, again for descending, a third time to
// restore the original order. Headers with data-sort="none" are not sortable.
// A cell's data-sort-value overrides its visible text as the sort key.
// Values that parse as numbers sort numerically; everything else sorts
// naturally ("EQUIP-9" before "EQUIP-10") and case-insensitively.
(function () {
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

    const style = document.createElement('style');
    style.textContent = `
        table.sortable th[data-sortable] { cursor: pointer; user-select: none; white-space: nowrap; }
        table.sortable th[data-sortable]::after { content: '\\2195'; opacity: .35; margin-left: .35em; font-size: .85em; }
        table.sortable th[aria-sort="ascending"]::after { content: '\\25B2'; opacity: 1; }
        table.sortable th[aria-sort="descending"]::after { content: '\\25BC'; opacity: 1; }
    `;
    document.head.appendChild(style);

    function cellKey(row, index) {
        const cell = row.cells[index];
        if (!cell) return '';
        return (cell.dataset.sortValue ?? cell.textContent).trim();
    }

    // '\u2014' is the em-dash shown in empty cells. Kept as an escape so this
    // file stays ASCII: servers often send .js without a charset.
    function isBlank(key) {
        return key === '' || key === '\u2014';
    }

    function compare(a, b) {
        const numA = Number(a), numB = Number(b);
        if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
        return collator.compare(a, b);
    }

    function init(table) {
        const tbody = table.tBodies[0];
        if (!tbody || !table.tHead) return;
        const originalOrder = Array.from(tbody.rows);
        const headers = Array.from(table.tHead.rows[0].cells);

        headers.forEach((th, index) => {
            if (th.dataset.sort === 'none' || !th.textContent.trim()) return;
            th.dataset.sortable = '';
            th.tabIndex = 0;
            th.title = th.title || 'Click to sort';

            const activate = () => {
                const next = { none: 'ascending', ascending: 'descending', descending: 'none' }[th.getAttribute('aria-sort') || 'none'];
                headers.forEach(h => h.removeAttribute('aria-sort'));

                let rows = originalOrder.slice();
                if (next !== 'none') {
                    th.setAttribute('aria-sort', next);
                    const dir = next === 'ascending' ? 1 : -1;
                    rows.sort((r1, r2) => {
                        const k1 = cellKey(r1, index), k2 = cellKey(r2, index);
                        const blank1 = isBlank(k1), blank2 = isBlank(k2);
                        if (blank1 || blank2) return blank1 - blank2;  // blanks sink in both directions
                        return dir * compare(k1, k2);
                    });
                }
                rows.forEach(r => tbody.appendChild(r));
            };

            th.addEventListener('click', activate);
            th.addEventListener('keydown', e => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
            });
        });
    }

    document.querySelectorAll('table.sortable').forEach(init);
})();
