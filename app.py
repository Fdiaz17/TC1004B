import streamlit as st
import pandas as pd
import mysql.connector
from mysql.connector import Error
import plotly.express as px

st.set_page_config(page_title="Café Central | Dashboard", page_icon="☕", layout="wide")

st.title("☕ Café Central")
st.caption("Tablero de control comercial · Sistema académico de gestión de ventas")

# Ajusta estos valores según la configuración de MySQL en tu XAMPP.
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "cafe_central",
}

@st.cache_resource
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def read_query(sql, params=None):
    conn = get_connection()
    return pd.read_sql(sql, conn, params=params)

try:
    # Validación de conexión
    conn = get_connection()
    if not conn.is_connected():
        st.error("No se pudo establecer conexión con MySQL. Verifica XAMPP y DB_CONFIG.")
        st.stop()

    with st.sidebar:
        st.header("Filtros")
        fechas = read_query("""
            SELECT MIN(DATE(fecha_pedido)) AS minimo,
                   MAX(DATE(fecha_pedido)) AS maximo
            FROM pedido
        """)
        min_date = pd.to_datetime(fechas.loc[0, "minimo"]).date()
        max_date = pd.to_datetime(fechas.loc[0, "maximo"]).date()
        rango = st.date_input("Periodo", value=(min_date, max_date),
                              min_value=min_date, max_value=max_date)
        estados = read_query("SELECT DISTINCT estado FROM pedido ORDER BY estado")["estado"].tolist()
        estados_sel = st.multiselect("Estado del pedido", estados, default=["Entregado"])

    if isinstance(rango, tuple) and len(rango) == 2:
        fecha_inicio, fecha_fin = rango
    else:
        fecha_inicio, fecha_fin = min_date, max_date

    if not estados_sel:
        st.warning("Selecciona al menos un estado para visualizar información.")
        st.stop()

    placeholders = ",".join(["%s"] * len(estados_sel))
    params = [fecha_inicio, fecha_fin, *estados_sel]

    resumen = read_query(f"""
        SELECT p.id_pedido, p.fecha_pedido, p.estado,
               CONCAT(c.nombre,' ',c.apellido) AS cliente,
               SUM(d.subtotal) AS subtotal,
               p.descuento, p.impuesto,
               SUM(d.subtotal) - p.descuento + p.impuesto AS total
        FROM pedido p
        JOIN cliente c ON c.id_cliente = p.id_cliente
        JOIN detalle_pedido d ON d.id_pedido = p.id_pedido
        WHERE DATE(p.fecha_pedido) BETWEEN %s AND %s
          AND p.estado IN ({placeholders})
        GROUP BY p.id_pedido, p.fecha_pedido, p.estado,
                 c.nombre, c.apellido, p.descuento, p.impuesto
        ORDER BY p.fecha_pedido
    """, params)

    if resumen.empty:
        st.info("No hay pedidos que coincidan con los filtros seleccionados.")
        st.stop()

    # Indicadores principales
    total_ventas = resumen["total"].sum()
    numero_pedidos = resumen["id_pedido"].nunique()
    ticket_promedio = total_ventas / numero_pedidos if numero_pedidos else 0
    clientes_atendidos = resumen["cliente"].nunique()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ventas del periodo", f"${total_ventas:,.2f}")
    c2.metric("Pedidos", f"{numero_pedidos:,}")
    c3.metric("Ticket promedio", f"${ticket_promedio:,.2f}")
    c4.metric("Clientes atendidos", f"{clientes_atendidos:,}")

    st.divider()
    left, right = st.columns(2)

    ventas_dia = (resumen.assign(fecha=pd.to_datetime(resumen["fecha_pedido"]).dt.date)
                  .groupby("fecha", as_index=False)["total"].sum())
    with left:
        st.subheader("Ventas por día")
        fig = px.line(ventas_dia, x="fecha", y="total", markers=True,
                      labels={"fecha": "Fecha", "total": "Ventas ($)"})
        st.plotly_chart(fig, use_container_width=True)

    ventas_estado = resumen.groupby("estado", as_index=False)["total"].sum()
    with right:
        st.subheader("Distribución por estado")
        fig = px.pie(ventas_estado, names="estado", values="total", hole=0.45)
        st.plotly_chart(fig, use_container_width=True)

    # Productos con mayor ingreso
    productos = read_query(f"""
        SELECT pr.nombre AS producto, cat.nombre AS categoria,
               SUM(d.cantidad) AS unidades,
               SUM(d.subtotal) AS ingresos
        FROM detalle_pedido d
        JOIN producto pr ON pr.id_producto = d.id_producto
        JOIN categoria cat ON cat.id_categoria = pr.id_categoria
        JOIN pedido p ON p.id_pedido = d.id_pedido
        WHERE DATE(p.fecha_pedido) BETWEEN %s AND %s
          AND p.estado IN ({placeholders})
        GROUP BY pr.id_producto, pr.nombre, cat.nombre
        ORDER BY ingresos DESC
        LIMIT 10
    """, params)

    st.subheader("Productos más vendidos por ingreso")
    fig = px.bar(productos, x="ingresos", y="producto", color="categoria",
                 orientation="h", labels={"ingresos": "Ingresos ($)", "producto": "Producto"})
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

    # Categorías y tabla
    cat = read_query(f"""
        SELECT ca.nombre AS categoria, SUM(d.subtotal) AS ventas
        FROM detalle_pedido d
        JOIN producto pr ON pr.id_producto = d.id_producto
        JOIN categoria ca ON ca.id_categoria = pr.id_categoria
        JOIN pedido p ON p.id_pedido = d.id_pedido
        WHERE DATE(p.fecha_pedido) BETWEEN %s AND %s
          AND p.estado IN ({placeholders})
        GROUP BY ca.id_categoria, ca.nombre
        ORDER BY ventas DESC
    """, params)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Ventas por categoría")
        st.plotly_chart(px.bar(cat, x="categoria", y="ventas",
                               labels={"categoria": "Categoría", "ventas": "Ventas ($)"}),
                        use_container_width=True)
    with col_b:
        st.subheader("Detalle de pedidos")
        st.dataframe(resumen[["id_pedido", "fecha_pedido", "cliente", "estado", "total"]],
                     use_container_width=True, hide_index=True)

    st.download_button(
        "Descargar pedidos filtrados (CSV)",
        data=resumen.to_csv(index=False).encode("utf-8-sig"),
        file_name="cafe_central_pedidos.csv",
        mime="text/csv"
    )

except Error as e:
    st.error("Error de conexión o consulta a MySQL.")
    st.code(str(e))
    st.info("Comprueba que MySQL esté iniciado en XAMPP, que la base cafe_central exista y que DB_CONFIG sea correcto.")
except Exception as e:
    st.error(f"Ocurrió un error inesperado: {e}")
