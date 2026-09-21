import pdfplumber

def extract_bom_from_pdf(file_path):
    """
    Extract tabular BOM data from a vector PDF using spatial clustering.
    Clusters text fragments by vertical Y-coordinates into distinct rows,
    and determines column boundaries from X-coordinate clustering.
    """
    line_items = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            if not words:
                continue
            
            # 1. Cluster text fragments by vertical Y-coordinates into distinct rows
            Y_TOLERANCE = 5.0
            rows = []
            for w in words:
                added = False
                for r in rows:
                    if abs(r['top'] - w['top']) <= Y_TOLERANCE:
                        r['words'].append(w)
                        added = True
                        break
                if not added:
                    rows.append({'top': w['top'], 'words': [w]})
            
            # Sort rows top-to-bottom
            rows.sort(key=lambda r: r['top'])
            
            # 2. Determine column boundaries from X-coordinate clustering across page
            all_x0 = sorted([w['x0'] for w in words])
            
            columns = []
            if all_x0:
                curr_cluster = [all_x0[0]]
                X_TOLERANCE = 15.0
                for x in all_x0[1:]:
                    if x - curr_cluster[-1] <= X_TOLERANCE:
                        curr_cluster.append(x)
                    else:
                        columns.append(sum(curr_cluster)/len(curr_cluster))
                        curr_cluster = [x]
                columns.append(sum(curr_cluster)/len(curr_cluster))
            
            # Sort columns left to right
            columns.sort()

            # Map each row's words to the detected columns
            structured_rows = []
            for r in rows:
                row_data = {col: [] for col in columns}
                for w in r['words']:
                    # Find closest column boundary
                    closest_col = min(columns, key=lambda col: abs(col - w['x0']))
                    row_data[closest_col].append(w['text'])
                
                # Join words in the same column block
                joined_row = [ ' '.join(row_data[col]) for col in columns ]
                structured_rows.append(joined_row)
            
            if len(structured_rows) < 2:
                continue
                
            # Use the first row as headers, lowercased and stripped of spaces
            headers = [str(h).lower().replace(' ', '-') for h in structured_rows[0]]
            
            # 3. Output normalized line items matching tabular structure
            for row in structured_rows[1:]:
                line_item = {}
                for idx, cell_value in enumerate(row):
                    header = headers[idx] if idx < len(headers) else f"col_{idx}"
                    if header:
                        line_item[header] = cell_value
                
                # Only add if it has some non-empty content
                if any(str(v).strip() for v in line_item.values()):
                    line_items.append(line_item)
                    
    return line_items
