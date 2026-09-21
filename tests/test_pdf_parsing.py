import os
import pytest
from reportlab.pdfgen import canvas
from bomkit.adapters.pdf_adapter import extract_bom_from_pdf

@pytest.fixture
def dummy_vector_pdf(tmp_path):
    pdf_path = tmp_path / "dummy_bom.pdf"
    c = canvas.Canvas(str(pdf_path))
    
    # Draw a 5-column table
    # Headers
    c.drawString(50, 800, "Item")
    c.drawString(150, 800, "Part-Number")
    c.drawString(300, 800, "Description")
    c.drawString(450, 800, "Qty")
    c.drawString(500, 800, "Ref")
    
    # Row 1
    c.drawString(50, 780, "1")
    c.drawString(150, 780, "PN-1001")
    c.drawString(300, 780, "Resistor 10K")
    c.drawString(450, 780, "10")
    c.drawString(500, 780, "R1")
    
    # Row 2
    c.drawString(50, 760, "2")
    c.drawString(150, 760, "PN-1002")
    c.drawString(300, 760, "Capacitor 1uF")
    c.drawString(450, 760, "5")
    c.drawString(500, 760, "C1")
    
    # Row 3
    c.drawString(50, 740, "3")
    c.drawString(150, 740, "PN-1003")
    c.drawString(300, 740, "Inductor 10uH")
    c.drawString(450, 740, "2")
    c.drawString(500, 740, "L1")
    
    c.save()
    return str(pdf_path)

def test_pdf_table_extraction(dummy_vector_pdf):
    # This must fail initially on a zero-byte adapter and pass after the fix
    line_items = extract_bom_from_pdf(dummy_vector_pdf)
    
    assert len(line_items) >= 3
    for item in line_items:
        assert 'part-number' in item
        assert item['part-number'] != ''
