const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, PageOrientation, HeadingLevel,
        BorderStyle, WidthType, ShadingType, PageNumber, PageBreak } = require('docx');

const data = JSON.parse(fs.readFileSync('/Users/wallyhuron/Downloads/ST Leaderboard/outlier_results.json', 'utf8'));

const border = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0 };

// Landscape US Letter: content width = 15840 - 1440 - 1440 = 12960 DXA
const TABLE_WIDTH = 12960;
// Columns: Pitcher(2400) Team(700) PT(600) Value(1100) Avg(1100) StdDev(900) Z(800) #P(700) Date(1400) = ~9700
// Spread wider for landscape
const COL_WIDTHS = [2600, 750, 650, 1200, 1200, 1000, 900, 760, 1500];
// Adjust last col to fill: 12960 - sum(others)
const sumOthers = COL_WIDTHS.slice(0, -1).reduce((a, b) => a + b, 0);
COL_WIDTHS[COL_WIDTHS.length - 1] = TABLE_WIDTH - sumOthers;

const HEADER_LABELS = ['Pitcher', 'Team', 'Pitch', 'Value', 'Pitcher Avg', 'Std Dev', 'Z-Score', '# Pitches', 'Game Date'];

function makeHeaderRow() {
    return new TableRow({
        tableHeader: true,
        children: HEADER_LABELS.map((label, i) => new TableCell({
            borders,
            width: { size: COL_WIDTHS[i], type: WidthType.DXA },
            shading: { fill: "D9D9D9", type: ShadingType.CLEAR },
            margins: { top: 40, bottom: 40, left: 80, right: 80 },
            children: [new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({ text: label, bold: true, font: "Arial", size: 17 })]
            })]
        }))
    });
}

function makeDataRow(r, idx) {
    const isAlt = idx % 2 === 1;
    const fill = isAlt ? "F2F2F2" : "FFFFFF";
    const unit = r.unit === 'RPM' ? '' : ' ft';
    const valFmt = r.unit === 'RPM' ? String(Math.round(r.value)) : r.value.toFixed(2);
    const avgFmt = r.unit === 'RPM' ? String(Math.round(r.mean)) : r.mean.toFixed(2);
    const stdFmt = r.unit === 'RPM' ? String(Math.round(r.std)) : r.std.toFixed(2);

    // Clean up game date - take just the date part
    let dateStr = r.game_date || '';
    if (dateStr.includes('T')) dateStr = dateStr.split('T')[0];
    // If it's a long datetime, try to extract just date
    if (dateStr.length > 10) {
        const m = dateStr.match(/\d{4}-\d{2}-\d{2}/);
        if (m) dateStr = m[0];
    }

    const cells = [
        r.pitcher,
        r.team,
        r.pitch_type,
        valFmt + (r.unit === 'RPM' ? ' RPM' : ' ft'),
        avgFmt + (r.unit === 'RPM' ? ' RPM' : ' ft'),
        stdFmt,
        r.z_score.toFixed(2),
        String(r.n_pitches),
        dateStr
    ];

    return new TableRow({
        children: cells.map((text, i) => new TableCell({
            borders,
            width: { size: COL_WIDTHS[i], type: WidthType.DXA },
            shading: { fill, type: ShadingType.CLEAR },
            margins: { top: 30, bottom: 30, left: 80, right: 80 },
            children: [new Paragraph({
                alignment: i >= 3 ? AlignmentType.CENTER : AlignmentType.LEFT,
                children: [new TextRun({ text, font: "Arial", size: 16 })]
            })]
        }))
    });
}

function makeTable(records) {
    const rows = [makeHeaderRow()];
    records.forEach((r, i) => rows.push(makeDataRow(r, i)));
    return new Table({
        width: { size: TABLE_WIDTH, type: WidthType.DXA },
        columnWidths: COL_WIDTHS,
        rows
    });
}

// Build document content
const children = [];

// Title
children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 100 },
    children: [new TextRun({ text: "ST 2026 Data Outlier Report", bold: true, font: "Arial", size: 40 })]
}));

children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
    children: [new TextRun({ text: "Spin Rate  |  Extension  |  Release Height  |  Release Side", font: "Arial", size: 24, color: "555555" })]
}));

children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 300 },
    children: [new TextRun({ text: "March 12, 2026", font: "Arial", size: 22, color: "777777" })]
}));

// Methodology
children.push(new Paragraph({
    spacing: { after: 120 },
    children: [new TextRun({ text: "Methodology", bold: true, font: "Arial", size: 24 })]
}));

children.push(new Paragraph({
    spacing: { after: 80 },
    children: [new TextRun({
        text: "Outliers were detected on a per-pitcher, per-pitch-type basis. For each group with at least 5 pitches, both Z-score and IQR (interquartile range) methods were applied. A pitch is flagged only if it exceeds both the Z-score threshold AND falls outside 2.0x IQR bounds, cross-validating to reduce false positives. Context-dependent absolute deviation minimums prevent flagging normal variation (e.g., Spin Rate must deviate by at least 200 RPM; Extension/RelZ/RelX by at least 0.3\u20130.4 ft). Changeups, splitters, and knuckleballs use a higher spin rate deviation threshold (300 RPM) due to naturally higher variance.",
        font: "Arial", size: 20
    })]
}));

children.push(new Paragraph({
    spacing: { after: 200 },
    children: [
        new TextRun({ text: "Confident Outliers", bold: true, font: "Arial", size: 20 }),
        new TextRun({ text: " (Z \u2265 3.0): High-confidence data errors that almost certainly need correction. ", font: "Arial", size: 20 }),
        new TextRun({ text: "Questionable Outliers", bold: true, font: "Arial", size: 20 }),
        new TextRun({ text: " (Z \u2265 2.2): Suspicious values that may be real or may be errors\u2014requires manual review.", font: "Arial", size: 20 }),
    ]
}));

// Section definitions
const sections = [
    { key: 'Spin Rate', title: 'Spin Rate Outliers', desc: 'Spin rate errors are the most common tracking issue. Values near 0 RPM or dramatically different from a pitcher\u2019s average are almost always sensor malfunctions.' },
    { key: 'Extension', title: 'Extension Outliers', desc: 'Extension measures how far toward home plate the pitcher releases the ball (typically 5.5\u20137.5 ft). Negative values or values above 10 ft are clearly erroneous.' },
    { key: 'Release Height', title: 'Release Height (RelZ) Outliers', desc: 'Release height is generally very consistent for a given pitcher across pitch types (typically 5\u20136.5 ft). Deviations of 0.3+ ft from a pitcher\u2019s norm for a pitch type are suspicious.' },
    { key: 'Release Side', title: 'Release Side (RelX) Outliers', desc: 'Release side measures lateral release point. Like release height, this is typically very consistent. Deviations of 0.3+ ft suggest tracking errors.' },
];

sections.forEach((sec, secIdx) => {
    if (secIdx > 0) {
        children.push(new Paragraph({ children: [new PageBreak()] }));
    }

    // Section heading
    children.push(new Paragraph({
        heading: HeadingLevel.HEADING_1,
        spacing: { before: 200, after: 120 },
        children: [new TextRun({ text: sec.title, bold: true, font: "Arial", size: 32 })]
    }));

    children.push(new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({ text: sec.desc, font: "Arial", size: 20, italics: true, color: "444444" })]
    }));

    const confRecs = data[sec.key].confident;
    const questRecs = data[sec.key].questionable;

    // Confident
    children.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 160, after: 100 },
        children: [new TextRun({ text: `Confident Outliers (${confRecs.length})`, bold: true, font: "Arial", size: 26 })]
    }));

    if (confRecs.length > 0) {
        children.push(makeTable(confRecs));
    } else {
        children.push(new Paragraph({
            spacing: { after: 100 },
            children: [new TextRun({ text: "No confident outliers detected.", font: "Arial", size: 20, italics: true })]
        }));
    }

    // Questionable
    children.push(new Paragraph({
        spacing: { before: 300 },
        children: []
    }));
    children.push(new Paragraph({
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 160, after: 100 },
        children: [new TextRun({ text: `Questionable Outliers (${questRecs.length})`, bold: true, font: "Arial", size: 26 })]
    }));

    if (questRecs.length > 0) {
        children.push(makeTable(questRecs));
    } else {
        children.push(new Paragraph({
            spacing: { after: 100 },
            children: [new TextRun({ text: "No questionable outliers detected.", font: "Arial", size: 20, italics: true })]
        }));
    }
});

// Summary page
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 200, after: 200 },
    children: [new TextRun({ text: "Summary", bold: true, font: "Arial", size: 32 })]
}));

// Summary table
const summaryColWidths = [3200, 2400, 2800, 2400];
const summaryHeaders = ['Metric', 'Confident', 'Questionable', 'Total'];
const summaryData = sections.map(sec => {
    const c = data[sec.key].confident.length;
    const q = data[sec.key].questionable.length;
    return [sec.key, String(c), String(q), String(c + q)];
});

const grandC = sections.reduce((s, sec) => s + data[sec.key].confident.length, 0);
const grandQ = sections.reduce((s, sec) => s + data[sec.key].questionable.length, 0);
summaryData.push(['Total', String(grandC), String(grandQ), String(grandC + grandQ)]);

const summaryRows = [
    new TableRow({
        tableHeader: true,
        children: summaryHeaders.map((h, i) => new TableCell({
            borders,
            width: { size: summaryColWidths[i], type: WidthType.DXA },
            shading: { fill: "D9D9D9", type: ShadingType.CLEAR },
            margins: { top: 60, bottom: 60, left: 120, right: 120 },
            children: [new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({ text: h, bold: true, font: "Arial", size: 22 })]
            })]
        }))
    }),
    ...summaryData.map((row, idx) => {
        const isLast = idx === summaryData.length - 1;
        return new TableRow({
            children: row.map((text, i) => new TableCell({
                borders,
                width: { size: summaryColWidths[i], type: WidthType.DXA },
                shading: { fill: isLast ? "E8E8E8" : (idx % 2 === 1 ? "F2F2F2" : "FFFFFF"), type: ShadingType.CLEAR },
                margins: { top: 50, bottom: 50, left: 120, right: 120 },
                children: [new Paragraph({
                    alignment: i >= 1 ? AlignmentType.CENTER : AlignmentType.LEFT,
                    children: [new TextRun({ text, bold: isLast, font: "Arial", size: 22 })]
                })]
            }))
        });
    })
];

children.push(new Table({
    width: { size: 10800, type: WidthType.DXA },
    columnWidths: summaryColWidths,
    rows: summaryRows
}));

children.push(new Paragraph({
    spacing: { before: 300 },
    children: [new TextRun({
        text: "Note: Confident outliers are high-priority corrections. Questionable outliers should be reviewed manually\u2014some may represent real pitch characteristics (e.g., occasional velocity dips, grip experiments) rather than tracking errors.",
        font: "Arial", size: 20, italics: true, color: "555555"
    })]
}));

// Create document
const doc = new Document({
    styles: {
        default: {
            document: { run: { font: "Arial", size: 20 } }
        },
        paragraphStyles: [
            { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 32, bold: true, font: "Arial" },
                paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
            { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 26, bold: true, font: "Arial" },
                paragraph: { spacing: { before: 180, after: 180 }, outlineLevel: 1 } },
        ]
    },
    sections: [{
        properties: {
            page: {
                size: {
                    width: 12240,
                    height: 15840,
                    orientation: PageOrientation.LANDSCAPE
                },
                margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 }
            }
        },
        headers: {
            default: new Header({
                children: [new Paragraph({
                    alignment: AlignmentType.RIGHT,
                    children: [new TextRun({ text: "ST 2026 Data Outlier Report", font: "Arial", size: 16, color: "999999", italics: true })]
                })]
            })
        },
        footers: {
            default: new Footer({
                children: [new Paragraph({
                    alignment: AlignmentType.CENTER,
                    children: [
                        new TextRun({ text: "Page ", font: "Arial", size: 16, color: "999999" }),
                        new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: "999999" })
                    ]
                })]
            })
        },
        children
    }]
});

Packer.toBuffer(doc).then(buffer => {
    fs.writeFileSync('/Users/wallyhuron/Downloads/ST Leaderboard/ST_2026_Outlier_Report.docx', buffer);
    console.log('Document created successfully!');
}).catch(err => {
    console.error('Error:', err);
});
