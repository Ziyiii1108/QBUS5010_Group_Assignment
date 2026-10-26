import os
from pathlib import Path
import numpy as np
import pandas as pd

from dash import Dash, dcc, html, dash_table, Input, Output
import plotly.express as px

app = Dash(__name__)

# Add server start
server = app.server

# Repository-local data file
BASE_DIR = Path(__file__).resolve().parent
FILE_PATH = BASE_DIR / "retail_inventory.xlsx"

# Load the three required sheets
sales = pd.read_excel(
    FILE_PATH,
    sheet_name="Sales_Transactions"
)

inventory = pd.read_excel(
    FILE_PATH,
    sheet_name="Inventory_Snapshot"
)

deliveries = pd.read_excel(
    FILE_PATH,
    sheet_name="Deliveries"
)

# Convert time 

sales["TransactionDate"] = pd.to_datetime(
    sales["TransactionDate"]
)

inventory["SnapshotDate"] = pd.to_datetime(
    inventory["SnapshotDate"]
)

inventory["ExpectedDeliveryDate"] = pd.to_datetime(
    inventory["ExpectedDeliveryDate"],
    errors="coerce"
)

inventory["PhysicalCountDate"] = pd.to_datetime(
    inventory["PhysicalCountDate"],
    errors="coerce"
)

deliveries["ExpectedDeliveryDate"] = pd.to_datetime(
    deliveries["ExpectedDeliveryDate"],
    errors="coerce"
)

deliveries["ActualDeliveryDate"] = pd.to_datetime(
    deliveries["ActualDeliveryDate"],
    errors="coerce"
)

print("Date columns converted.")


for col in [
    "Amount",
    "QuantitySold",
    "DerivedUnitPrice"
]:
    sales[col] = pd.to_numeric(
        sales[col],
        errors="coerce"
    )

for col in [
    "OpeningStock7D",
    "Sales7D",
    "Received7D",
    "CurrentStock",
    "ReorderPoint",
    "MaxStockLevel",
    "IncomingStock",
    "SalesVelocity7D",
    "DaysLeft",
    "RecordedStock",
    "PhysicalCount",
    "InventoryDiscrepancy",
    "CountMatch",
    "SKUInventoryAccuracyPct"
]:
    inventory[col] = pd.to_numeric(
        inventory[col],
        errors="coerce"
    )

deliveries["DeliveredQuantity"] = pd.to_numeric(
    deliveries["DeliveredQuantity"],
    errors="coerce"
)

print("Numeric columns converted.")


SNAPSHOT_DATE = inventory["SnapshotDate"].max()

CATEGORY_OPTIONS = sorted(
    inventory["Category"]
    .dropna()
    .unique()
    .tolist()
)

print("Snapshot date:", SNAPSHOT_DATE.date())
print("Categories:", CATEGORY_OPTIONS)


def calculate_dashboard_data(
    window_days=7,
    category="All",
    search_text=""
):
    window_days = int(window_days)

    start_date = (
        SNAPSHOT_DATE
        - pd.Timedelta(days=window_days - 1)
    )

    filtered_sales = sales[
        (sales["TransactionDate"] >= start_date)
        & (sales["TransactionDate"] <= SNAPSHOT_DATE)
    ].copy()

    inv = inventory.copy()

    if category != "All":
        filtered_sales = filtered_sales[
            filtered_sales["Category"] == category
        ]

        inv = inv[
            inv["Category"] == category
        ]

    if search_text:
        text = search_text.strip().lower()

        inv = inv[
            inv["ItemPurchased"]
            .str.lower()
            .str.contains(text, na=False)
            |
            inv["SKU"]
            .str.lower()
            .str.contains(text, na=False)
        ]

        filtered_sales = filtered_sales[
            filtered_sales["SKU"].isin(inv["SKU"])
        ]

    sales_summary = (
        filtered_sales
        .groupby("SKU", as_index=False)
        .agg(
            WindowSales=("QuantitySold", "sum"),
            Revenue=("Amount", "sum")
        )
    )

    inv = inv.merge(
        sales_summary,
        on="SKU",
        how="left"
    )

    inv["WindowSales"] = inv["WindowSales"].fillna(0)
    inv["Revenue"] = inv["Revenue"].fillna(0)

    inv["SalesVelocity"] = (
        inv["WindowSales"] / window_days
    )

    inv["DynamicDaysLeft"] = np.where(
        inv["SalesVelocity"] > 0,
        inv["CurrentStock"] / inv["SalesVelocity"],
        999
    )

    return inv, filtered_sales


def determine_status(row):
    if row["CurrentStock"] <= 0:
        return "Out of Stock"

    if row["CurrentStock"] > row["MaxStockLevel"]:
        return "Overstock"

    if row["DynamicDaysLeft"] < 3:
        return "Urgent Reorder"

    if (
        row["DynamicDaysLeft"] < 7
        or row["CurrentStock"] <= row["ReorderPoint"]
    ):
        return "Reorder Soon"

    return "Healthy"


STATUS_COLOURS = {
    "Out of Stock": "#E53935",
    "Urgent Reorder": "#FF9800",
    "Reorder Soon": "#FBC02D",
    "Healthy": "#45B97C",
    "Overstock": "#3E8EDE"
}


def make_inventory_scatter(inv):
    fig = px.scatter(
        inv,
        x="SalesVelocity",
        y="CurrentStock",
        color="DynamicStatus",
        hover_name="ItemPurchased",
        hover_data={
            "SKU": True,
            "Category": True,
            "CurrentStock": True,
            "SalesVelocity": ":.2f",
            "DynamicDaysLeft": ":.1f"
        },
        color_discrete_map=STATUS_COLOURS,
        labels={
            "SalesVelocity": "Sales velocity (units/day)",
            "CurrentStock": "Current stock (units)",
            "DynamicStatus": "Status"
        }
    )

    fig.update_traces(
        marker={
            "size": 12,
            "line": {
                "width": 1,
                "color": "white"
            }
        }
    )

    fig.update_layout(
        template="plotly_white",
        height=470,
        margin=dict(l=20, r=20, t=25, b=20),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0
        )
    )

    return fig


def make_fastest_chart(inv):
    fastest = (
        inv
        .sort_values(
            "SalesVelocity",
            ascending=False
        )
        .head(10)
        .sort_values(
            "SalesVelocity",
            ascending=True
        )
    )

    fig = px.bar(
        fastest,
        x="SalesVelocity",
        y="ItemPurchased",
        orientation="h",
        color="Category",
        labels={
            "SalesVelocity": "Units sold per day",
            "ItemPurchased": ""
        }
    )

    fig.update_layout(
        template="plotly_white",
        showlegend=False,
        height=470,
        margin=dict(l=10, r=10, t=15, b=20)
    )

    return fig


PRIORITY_RANK = {
    "Out of Stock": 1,
    "Urgent Reorder": 2,
    "Reorder Soon": 3,
    "Healthy": 4,
    "Overstock": 5
}


def prepare_priority_table(
    inv,
    selected_status
):
    priority = inv.copy()

    if selected_status != "All":
        priority = priority[
            priority["DynamicStatus"]
            == selected_status
        ]

    priority["PriorityRank"] = (
        priority["DynamicStatus"]
        .map(PRIORITY_RANK)
    )

    priority = priority.sort_values(
        [
            "PriorityRank",
            "DynamicDaysLeft"
        ],
        ascending=[
            True,
            True
        ]
    )

    priority["SalesVelocity"] = (
        priority["SalesVelocity"]
        .round(2)
    )

    priority["DynamicDaysLeft"] = (
        priority["DynamicDaysLeft"]
        .replace(999, np.nan)
        .round(1)
    )

    priority["Action"] = np.where(
        priority["DynamicStatus"].isin([
            "Out of Stock",
            "Urgent Reorder",
            "Reorder Soon"
        ]),
        "Order now",
        "—"
    )

    columns = [
        "SKU",
        "ItemPurchased",
        "CurrentStock",
        "WindowSales",
        "SalesVelocity",
        "IncomingStock",
        "DynamicDaysLeft",
        "DynamicStatus",
        "Action"
    ]

    return (
        priority[columns]
        .replace({np.nan: None})
        .to_dict("records")
    )


def make_delivery_demand_chart(
    inv,
    window_days
):
    selected_skus = inv["SKU"].tolist()

    delivered = deliveries[
        deliveries["SKU"].isin(selected_skus)
        & (
            deliveries["DeliveryStatus"]
            == "Received"
        )
    ].copy()

    start_date = (
        SNAPSHOT_DATE
        - pd.Timedelta(
            days=int(window_days) - 1
        )
    )

    delivered = delivered[
        (
            delivered["ActualDeliveryDate"]
            >= start_date
        )
        &
        (
            delivered["ActualDeliveryDate"]
            <= SNAPSHOT_DATE
        )
    ]

    delivery_summary = (
        delivered
        .groupby("SKU", as_index=False)
        ["DeliveredQuantity"]
        .sum()
    )

    demand_summary = inv[
        [
            "SKU",
            "ItemPurchased",
            "WindowSales"
        ]
    ].copy()

    result = demand_summary.merge(
        delivery_summary,
        on="SKU",
        how="left"
    )

    result["DeliveredQuantity"] = (
        result["DeliveredQuantity"]
        .fillna(0)
    )

    result["Activity"] = (
        result["WindowSales"]
        + result["DeliveredQuantity"]
    )

    result = (
        result
        .sort_values(
            "Activity",
            ascending=False
        )
        .head(10)
    )

    long_df = result.melt(
        id_vars=[
            "SKU",
            "ItemPurchased"
        ],
        value_vars=[
            "WindowSales",
            "DeliveredQuantity"
        ],
        var_name="Metric",
        value_name="Units"
    )

    long_df["Metric"] = (
        long_df["Metric"]
        .replace({
            "WindowSales": "Sold (Demand)",
            "DeliveredQuantity": "Delivered (Supply)"
        })
    )

    fig = px.bar(
        long_df,
        x="Units",
        y="ItemPurchased",
        color="Metric",
        orientation="h",
        barmode="group",
        labels={
            "ItemPurchased": "",
            "Metric": ""
        }
    )

    fig.update_layout(
        template="plotly_white",
        height=430,
        margin=dict(l=10, r=10, t=20, b=20),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02
        )
    )

    return fig


def make_discrepancy_chart(inv):
    discrepancies = (
        inv[
            inv["InventoryDiscrepancy"] != 0
        ]
        .copy()
    )

    discrepancies["AbsDifference"] = (
        discrepancies["InventoryDiscrepancy"]
        .abs()
    )

    discrepancies = (
        discrepancies
        .sort_values(
            "AbsDifference",
            ascending=False
        )
        .head(10)
    )

    fig = px.bar(
        discrepancies,
        x="InventoryDiscrepancy",
        y="ItemPurchased",
        orientation="h",
        color="InventoryDiscrepancy",
        color_continuous_scale=[
            "#E53935",
            "#F5F5F5",
            "#F2B134"
        ],
        labels={
            "InventoryDiscrepancy":
                "Physical minus recorded stock",
            "ItemPurchased": ""
        }
    )

    fig.update_layout(
        template="plotly_white",
        coloraxis_showscale=False,
        height=300,
        margin=dict(l=10, r=10, t=20, b=20)
    )

    return fig


app = Dash(__name__)
app.title = "Store Inventory Dashboard"

PAGE_STYLE = {
    "backgroundColor": "#F5F7FA",
    "minHeight": "100vh",
    "fontFamily": "Arial, sans-serif",
    "padding": "28px"
}

MAIN_CONTAINER = {
    "maxWidth": "1450px",
    "margin": "0 auto"
}

CARD_STYLE = {
    "backgroundColor": "white",
    "borderRadius": "18px",
    "padding": "22px",
    "boxShadow":
        "0 4px 16px rgba(0,0,0,0.05)"
}

KPI_STYLE = {
    "backgroundColor": "white",
    "borderRadius": "16px",
    "padding": "22px",
    "boxShadow":
        "0 3px 12px rgba(0,0,0,0.05)",
    "minHeight": "120px"
}

LABEL_STYLE = {
    "fontSize": "13px",
    "fontWeight": "700",
    "color": "#5C667A",
    "marginBottom": "6px"
}

VALUE_STYLE = {
    "fontSize": "34px",
    "fontWeight": "700",
    "color": "#111827",
    "margin": "8px 0"
}


header = html.Div(
    style={
        **CARD_STYLE,
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
        "marginBottom": "18px"
    },
    children=[
        html.Div([
            html.Div(
                "◆ XXX STORE INVENTORY",
                style={
                    "fontWeight": "800",
                    "fontSize": "22px",
                    "color": "#172033"
                }
            ),
            html.Div(
                "Store-level inventory and replenishment decision dashboard",
                style={
                    "color": "#8A94A6",
                    "fontSize": "13px",
                    "marginTop": "5px"
                }
            )
        ]),
        html.Div(
            f"● Inventory snapshot: "
            f"{SNAPSHOT_DATE.strftime('%d %b %Y')}",
            style={
                "fontSize": "13px",
                "color": "#798397"
            }
        )
    ]
)


filters = html.Div(
    style={
        **CARD_STYLE,
        "display": "grid",
        "gridTemplateColumns":
            "1fr 1fr 2fr",
        "gap": "20px",
        "marginBottom": "20px"
    },
    children=[
        html.Div([
            html.Div(
                "Sales Window",
                style=LABEL_STYLE
            ),
            dcc.Dropdown(
                id="window-filter",
                options=[
                    {
                        "label": "Last 7 days",
                        "value": 7
                    },
                    {
                        "label": "Last 30 days",
                        "value": 30
                    },
                    {
                        "label": "Last 90 days",
                        "value": 90
                    }
                ],
                value=7,
                clearable=False
            )
        ]),

        html.Div([
            html.Div(
                "Category",
                style=LABEL_STYLE
            ),
            dcc.Dropdown(
                id="category-filter",
                options=[
                    {
                        "label": "All Categories",
                        "value": "All"
                    }
                ]
                + [
                    {
                        "label": c,
                        "value": c
                    }
                    for c in CATEGORY_OPTIONS
                ],
                value="All",
                clearable=False
            )
        ]),

        html.Div([
            html.Div(
                "Search SKU or Product",
                style=LABEL_STYLE
            ),
            dcc.Input(
                id="product-search",
                type="text",
                placeholder=
                    "Search SKU or Product...",
                debounce=True,
                style={
                    "width": "100%",
                    "height": "38px",
                    "borderRadius": "8px",
                    "border":
                        "1px solid #CBD2DC",
                    "padding": "0 14px",
                    "boxSizing": "border-box"
                }
            )
        ])
    ]
)


kpi_cards = html.Div(
    style={
        "display": "grid",
        "gridTemplateColumns":
            "repeat(4, 1fr)",
        "gap": "18px",
        "marginBottom": "20px"
    },
    children=[
        html.Div(
            style={
                **KPI_STYLE,
                "background":
                    "linear-gradient(135deg,#1473E6,#2989FF)",
                "color": "white"
            },
            children=[
                html.Div(
                    "Urgent reorder",
                    style={
                        "fontSize": "14px",
                        "fontWeight": "700"
                    }
                ),
                html.Div(
                    id="kpi-urgent",
                    style={
                        **VALUE_STYLE,
                        "color": "white"
                    }
                ),
                html.Div(
                    "SKUs with less than 3 days of stock",
                    style={
                        "fontSize": "12px",
                        "opacity": 0.9
                    }
                )
            ]
        ),

        html.Div(
            style=KPI_STYLE,
            children=[
                html.Div(
                    "Out of stock",
                    style=LABEL_STYLE
                ),
                html.Div(
                    id="kpi-oos",
                    style=VALUE_STYLE
                ),
                html.Div(
                    "SKUs with zero units",
                    style={
                        "fontSize": "12px",
                        "color": "#687386"
                    }
                )
            ]
        ),

        html.Div(
            style=KPI_STYLE,
            children=[
                html.Div(
                    "Overstocked",
                    style=LABEL_STYLE
                ),
                html.Div(
                    id="kpi-overstock",
                    style=VALUE_STYLE
                ),
                html.Div(
                    "SKUs above maximum stock level",
                    style={
                        "fontSize": "12px",
                        "color": "#687386"
                    }
                )
            ]
        ),

        html.Div(
            style=KPI_STYLE,
            children=[
                html.Div(
                    "Inventory accuracy",
                    style=LABEL_STYLE
                ),
                html.Div(
                    id="kpi-accuracy",
                    style=VALUE_STYLE
                ),
                html.Div(
                    "Physical count match rate",
                    style={
                        "fontSize": "12px",
                        "color": "#687386"
                    }
                )
            ]
        )
    ]
)


main_charts = html.Div(
    style={
        "display": "grid",
        "gridTemplateColumns": "2fr 1fr",
        "gap": "20px",
        "marginBottom": "20px"
    },
    children=[
        html.Div(
            style=CARD_STYLE,
            children=[
                html.H3(
                    "Inventory Level vs. Sales Velocity",
                    style={
                        "marginTop": 0,
                        "marginBottom": "2px"
                    }
                ),
                html.P(
                    "Each point represents one SKU.",
                    style={
                        "fontSize": "12px",
                        "color": "#7C8596"
                    }
                ),
                dcc.Graph(
                    id="inventory-scatter",
                    config={
                        "displayModeBar": False
                    }
                )
            ]
        ),

        html.Div(
            style=CARD_STYLE,
            children=[
                html.H3(
                    "Fastest-Moving SKUs",
                    style={
                        "marginTop": 0,
                        "marginBottom": "2px"
                    }
                ),
                html.P(
                    "Average units sold per day",
                    style={
                        "fontSize": "12px",
                        "color": "#7C8596"
                    }
                ),
                dcc.Graph(
                    id="fastest-chart",
                    config={
                        "displayModeBar": False
                    }
                )
            ]
        )
    ]
)


replenishment_section = html.Div(
    style={
        **CARD_STYLE,
        "marginBottom": "20px"
    },
    children=[
        html.H3(
            "Replenishment Priority",
            style={
                "marginTop": 0,
                "marginBottom": "3px"
            }
        ),

        html.Div(
            id="priority-summary",
            style={
                "fontSize": "12px",
                "color": "#778196",
                "marginBottom": "14px"
            }
        ),

        dcc.RadioItems(
            id="status-filter",
            options=[
                {
                    "label": "All",
                    "value": "All"
                },
                {
                    "label": "Out of Stock",
                    "value": "Out of Stock"
                },
                {
                    "label": "Urgent Reorder",
                    "value": "Urgent Reorder"
                },
                {
                    "label": "Reorder Soon",
                    "value": "Reorder Soon"
                },
                {
                    "label": "Healthy",
                    "value": "Healthy"
                },
                {
                    "label": "Overstock",
                    "value": "Overstock"
                }
            ],
            value="All",
            inline=True,
            style={
                "marginBottom": "16px"
            },
            inputStyle={
                "marginRight": "5px",
                "marginLeft": "12px"
            }
        ),

        dash_table.DataTable(
            id="priority-table",
            columns=[
                {
                    "name": "SKU",
                    "id": "SKU"
                },
                {
                    "name": "Product",
                    "id": "ItemPurchased"
                },
                {
                    "name": "Current Stock",
                    "id": "CurrentStock"
                },
                {
                    "name": "Sales",
                    "id": "WindowSales"
                },
                {
                    "name": "Velocity",
                    "id": "SalesVelocity"
                },
                {
                    "name": "Incoming",
                    "id": "IncomingStock"
                },
                {
                    "name": "Days Left",
                    "id": "DynamicDaysLeft"
                },
                {
                    "name": "Status",
                    "id": "DynamicStatus"
                },
                {
                    "name": "Action",
                    "id": "Action"
                }
            ],
            page_size=12,
            sort_action="native",
            style_table={
                "overflowX": "auto"
            },
            style_header={
                "backgroundColor": "#F7F8FA",
                "fontWeight": "700",
                "border": "none",
                "color": "#687386",
                "fontSize": "12px"
            },
            style_cell={
                "padding": "13px",
                "border": "none",
                "borderBottom":
                    "1px solid #EEF0F3",
                "fontSize": "13px",
                "textAlign": "left",
                "fontFamily": "Arial"
            },
            style_data_conditional=[
                {
                    "if": {
                        "filter_query":
                            '{DynamicStatus} = "Out of Stock"',
                        "column_id":
                            "DynamicStatus"
                    },
                    "backgroundColor":
                        "#FDE7E7",
                    "color":
                        "#C62828",
                    "fontWeight":
                        "700"
                },
                {
                    "if": {
                        "filter_query":
                            '{DynamicStatus} = "Urgent Reorder"',
                        "column_id":
                            "DynamicStatus"
                    },
                    "backgroundColor":
                        "#FFF4D6",
                    "color":
                        "#B7791F",
                    "fontWeight":
                        "700"
                },
                {
                    "if": {
                        "filter_query":
                            '{DynamicStatus} = "Overstock"',
                        "column_id":
                            "DynamicStatus"
                    },
                    "backgroundColor":
                        "#E7F1FF",
                    "color":
                        "#2563EB",
                    "fontWeight":
                        "700"
                },
                {
                    "if": {
                        "filter_query":
                            '{Action} = "Order now"',
                        "column_id":
                            "Action"
                    },
                    "backgroundColor":
                        "#E53935",
                    "color":
                        "white",
                    "fontWeight":
                        "700",
                    "textAlign":
                        "center"
                }
            ]
        )
    ]
)


bottom_panels = html.Div(
    style={
        "display": "grid",
        "gridTemplateColumns": "1fr 1fr",
        "gap": "20px"
    },
    children=[
        html.Div(
            style=CARD_STYLE,
            children=[
                html.H3(
                    "Delivery vs. Demand",
                    style={
                        "marginTop": 0,
                        "marginBottom": "2px"
                    }
                ),
                html.P(
                    "Units delivered vs. units sold",
                    style={
                        "fontSize": "12px",
                        "color": "#7C8596"
                    }
                ),
                dcc.Graph(
                    id="delivery-demand-chart",
                    config={
                        "displayModeBar": False
                    }
                )
            ]
        ),

        html.Div(
            style=CARD_STYLE,
            children=[
                html.H3(
                    "Inventory Discrepancies",
                    style={
                        "marginTop": 0,
                        "marginBottom": "2px"
                    }
                ),
                html.P(
                    id="physical-count-label",
                    style={
                        "fontSize": "12px",
                        "color": "#7C8596"
                    }
                ),
                html.Div(
                    id="accuracy-mini-cards"
                ),
                dcc.Graph(
                    id="discrepancy-chart",
                    config={
                        "displayModeBar": False
                    }
                )
            ]
        )
    ]
)


app.layout = html.Div(
    style=PAGE_STYLE,
    children=[
        html.Div(
            style=MAIN_CONTAINER,
            children=[
                header,
                filters,
                kpi_cards,
                main_charts,
                replenishment_section,
                bottom_panels
            ]
        )
    ]
)

print("Dashboard layout created.")


def make_accuracy_cards(
    accuracy,
    total_missing,
    total_surplus
):
    return html.Div(
        style={
            "display": "grid",
            "gridTemplateColumns":
                "repeat(3, 1fr)",
            "gap": "10px",
            "marginBottom": "12px"
        },
        children=[
            html.Div(
                style={
                    "background": "#F8FAFC",
                    "padding": "14px",
                    "borderRadius": "12px",
                    "textAlign": "center"
                },
                children=[
                    html.Div(
                        f"{accuracy:.1f}%",
                        style={
                            "fontSize": "23px",
                            "fontWeight": "700"
                        }
                    ),
                    html.Div(
                        "Accuracy rate",
                        style={
                            "fontSize": "11px",
                            "color": "#7C8596"
                        }
                    )
                ]
            ),

            html.Div(
                style={
                    "background": "#FFF2F2",
                    "padding": "14px",
                    "borderRadius": "12px",
                    "textAlign": "center"
                },
                children=[
                    html.Div(
                        f"-{int(total_missing)}",
                        style={
                            "fontSize": "23px",
                            "fontWeight": "700",
                            "color": "#D64545"
                        }
                    ),
                    html.Div(
                        "Units missing",
                        style={
                            "fontSize": "11px",
                            "color": "#7C8596"
                        }
                    )
                ]
            ),

            html.Div(
                style={
                    "background": "#FFF8E6",
                    "padding": "14px",
                    "borderRadius": "12px",
                    "textAlign": "center"
                },
                children=[
                    html.Div(
                        f"+{int(total_surplus)}",
                        style={
                            "fontSize": "23px",
                            "fontWeight": "700",
                            "color": "#C58B16"
                        }
                    ),
                    html.Div(
                        "Units surplus",
                        style={
                            "fontSize": "11px",
                            "color": "#7C8596"
                        }
                    )
                ]
            )
        ]
    )


@app.callback(
    Output("kpi-urgent", "children"),
    Output("kpi-oos", "children"),
    Output("kpi-overstock", "children"),
    Output("kpi-accuracy", "children"),
    Output("inventory-scatter", "figure"),
    Output("fastest-chart", "figure"),
    Output("priority-table", "data"),
    Output("priority-summary", "children"),
    Output("delivery-demand-chart", "figure"),
    Output("physical-count-label", "children"),
    Output("accuracy-mini-cards", "children"),
    Output("discrepancy-chart", "figure"),
    Input("window-filter", "value"),
    Input("category-filter", "value"),
    Input("product-search", "value"),
    Input("status-filter", "value")
)
def update_dashboard(
    window_days,
    category,
    search_text,
    selected_status
):
    inv, _ = calculate_dashboard_data(
        window_days,
        category,
        search_text or ""
    )

    inv["DynamicStatus"] = inv.apply(
        determine_status,
        axis=1
    )

    urgent = (
        inv["DynamicStatus"]
        .eq("Urgent Reorder")
        .sum()
    )

    out_of_stock = (
        inv["DynamicStatus"]
        .eq("Out of Stock")
        .sum()
    )

    overstock = (
        inv["DynamicStatus"]
        .eq("Overstock")
        .sum()
    )

    accuracy = (
        inv["CountMatch"].mean() * 100
        if len(inv)
        else 0
    )

    scatter_fig = make_inventory_scatter(inv)

    fastest_fig = make_fastest_chart(inv)

    priority_data = prepare_priority_table(
        inv,
        selected_status
    )

    priority_summary = (
        f"Showing {len(priority_data)} of "
        f"{len(inv)} SKUs · "
        f"{window_days}-day sales window"
    )

    delivery_fig = (
        make_delivery_demand_chart(
            inv,
            window_days
        )
    )

    physical_date = (
        inventory["PhysicalCountDate"]
        .max()
    )

    physical_label = (
        "Recorded vs. physical count differences · "
        f"Last physical count: "
        f"{physical_date.strftime('%d %b %Y')}"
    )

    total_missing = abs(
        inv.loc[
            inv["InventoryDiscrepancy"] < 0,
            "InventoryDiscrepancy"
        ].sum()
    )

    total_surplus = (
        inv.loc[
            inv["InventoryDiscrepancy"] > 0,
            "InventoryDiscrepancy"
        ].sum()
    )

    mini_cards = make_accuracy_cards(
        accuracy,
        total_missing,
        total_surplus
    )

    discrepancy_fig = (
        make_discrepancy_chart(inv)
    )

    return (
        str(int(urgent)),
        str(int(out_of_stock)),
        str(int(overstock)),
        f"{accuracy:.1f}%",
        scatter_fig,
        fastest_fig,
        priority_data,
        priority_summary,
        delivery_fig,
        physical_label,
        mini_cards,
        discrepancy_fig
    )


server = app.server

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
