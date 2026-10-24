"""Frozen research-only recipient block selection; no truth or customer inputs."""
from collections import defaultdict
import re
import statistics

LABEL = re.compile(r'^\s*(?:bill[\s_]+to|billed\s+to|invoice\s+to|sold\s+to|'
                   r'billing\s+address|customer(?:\s+address)?|recipient|account\s+holder)\b\s*:?\s*', re.I)
STOP = re.compile(r'^\s*(?:ship[\s_]+to|seller|supplier|issuer|from|date|due\s+date|'
                  r'invoice\s+(?:number|no)|description|quantity|subtotal|total|'
                  r'payment|opening\s+balance|transactions?|tel|phone|email|site)\b', re.I)


def lines_from_words(words):
    groups = defaultdict(list)
    for i, w in enumerate(words):
        if w['w'] > 0 and w['h'] > 0 and w['text'].strip():
            groups[w['line']].append(i)
    result = []
    for indices in groups.values():
        indices.sort(key=lambda i: (words[i]['x'], i))
        ws = [words[i] for i in indices]
        x, y = min(w['x'] for w in ws), min(w['y'] for w in ws)
        result.append(dict(indices=indices, text=' '.join(w['text'] for w in ws), x=x, y=y,
                           w=max(w['x']+w['w'] for w in ws)-x,
                           h=max(w['y']+w['h'] for w in ws)-y))
    return sorted(result, key=lambda r: (r['y'], r['x']))


def canonical_ocr_words(lines):
    """Lossless token references, not invented word boxes: every token keeps its line box."""
    words = []
    for source_line_index, line in enumerate(lines):
        for token_index, match in enumerate(re.finditer(r'\S+', line['text'])):
            words.append({k: line[k] for k in ('x', 'y', 'w', 'h')} | dict(
                text=match[0], line=source_line_index, source_line_index=source_line_index,
                token_index=token_index, char_start=match.start(), char_end=match.end()))
    return words


def select(words, page_size):
    """One label, up to six adjacent lines. Multiple labels/branches return conflict."""
    if not page_size or len(page_size) != 2 or min(page_size) <= 0:
        return dict(status='invalid_geometry', indices=[])
    lines = lines_from_words(words)
    anchors = [(i, LABEL.match(line['text'])) for i, line in enumerate(lines) if LABEL.match(line['text'])]
    if not anchors:
        return dict(status='no_label', indices=[])
    if len(anchors) != 1:
        return dict(status='conflict', indices=[])
    mh = statistics.median(line['h'] for line in lines)
    current, match = anchors[0]
    anchor = lines[current]
    # Preserve original indices. Only label tokens are removed from a same-line suffix.
    selected = []
    offset = 0
    for index in anchor['indices']:
        end = offset + len(words[index]['text'])
        if end > match.end():
            selected.append(index)
        offset = end + 1
    used = {current}
    for _ in range(6):
        prev = lines[current]
        options = []
        for i, line in enumerate(lines):
            if i in used:
                continue
            gap = line['y'] - (prev['y'] + prev['h'])
            overlap = max(0, min(prev['x']+prev['w'], line['x']+line['w'])-max(prev['x'], line['x']))
            if (-.25*mh <= gap <= 2*mh and line['y'] > prev['y'] and
                    (overlap >= .25*min(prev['w'], line['w']) or abs(prev['x']-line['x']) <= 2*mh)):
                options.append((line['y'], abs(line['x']-prev['x']), i))
        if not options:
            break
        options.sort()
        if len(options) > 1 and abs(options[0][0]-options[1][0]) <= .5*mh:
            return dict(status='conflict', indices=[])
        current = options[0][2]
        line = lines[current]
        if LABEL.match(line['text']) or STOP.match(line['text']):
            break
        selected.extend(line['indices'])
        used.add(current)
    if len(used) == 7:
        # A bounded answer must not silently call a possibly truncated block complete.
        return dict(status='limit', indices=[])
    return dict(status='selected' if selected else 'no_adjacent_text', indices=selected)
