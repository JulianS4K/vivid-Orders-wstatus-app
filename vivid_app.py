import os
import requests
import csv
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from dotenv import load_dotenv
import threading
import time
from datetime import datetime, timedelta
import glob

load_dotenv()

class VividMasterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Vivid Seats Pro: Master Manager (Dual-Fetch & URL Transfer)")
        self.root.geometry("1300x950")
        
        self.api_token = os.getenv("VIVID_API_TOKEN", "")
        self.enriched_data = {} 
        self.phase1_results = [] 
        self.current_filename = ""
        self.sort_reverse = False

        self.setup_ui()
        self.auto_load_existing_csvs()

    def setup_ui(self):
        self.paned_window = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill="both", expand=True)

        self.left_frame = tk.Frame(self.paned_window)
        self.right_frame = tk.Frame(self.paned_window, width=380, bg="#f4f7f6", padx=15, pady=15)
        self.paned_window.add(self.left_frame)
        self.paned_window.add(self.right_frame)

        self.notebook = ttk.Notebook(self.left_frame)
        self.notebook.pack(fill="both", expand=True)

        self.main_tab = tk.Frame(self.notebook)
        self.log_tab = tk.Frame(self.notebook)
        self.notebook.add(self.main_tab, text="Order Management")
        self.notebook.add(self.log_tab, text="Activity Log")

        self.ctrl_frame = tk.Frame(self.main_tab, pady=10)
        self.ctrl_frame.pack(fill="x", padx=10)

        self.btn_fetch = tk.Button(self.ctrl_frame, text="RUN DUAL FETCH (Shipment -> Retransfer)", 
                                   command=self.start_dual_fetch, bg="#27ae60", fg="white", font=("Arial", 9, "bold"))
        self.btn_fetch.pack(side="left", padx=5)

        self.hide_past_var = tk.BooleanVar(value=True)
        self.hide_past_check = tk.Checkbutton(self.ctrl_frame, text="Hide Past (-12h)", variable=self.hide_past_var, command=self.refresh_table_view)
        self.hide_past_check.pack(side="left", padx=10)

        self.info_label = tk.Label(self.ctrl_frame, text="Ready", fg="blue")
        self.info_label.pack(side="right", padx=10)

        self.tree1 = ttk.Treeview(self.main_tab, columns=("id", "event", "date", "qty", "status", "transferable"), show="headings", height=15)
        headers = ["Order ID", "Event", "Event Date", "Qty", "Status", "URL Transfer?"]
        for col, head in zip(self.tree1["columns"], headers):
            self.tree1.heading(col, text=head, command=lambda c=col: self.sort_column(c))
            self.tree1.column(col, width=130)
        self.tree1.pack(fill="both", expand=True, padx=10, pady=5)
        self.tree1.bind("<<TreeviewSelect>>", self.on_order_selected)

        self.tree2 = ttk.Treeview(self.main_tab, columns=("field", "value"), show="headings", height=10)
        self.tree2.heading("field", text="Field Name"); self.tree2.heading("value", text="Value")
        self.tree2.column("field", width=150); self.tree2.column("value", width=500)
        self.tree2.pack(fill="both", expand=True, padx=10, pady=5)

        self.history_text = tk.Text(self.log_tab, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.history_text.pack(fill="both", expand=True, padx=10, pady=10)

        # --- RIGHT SIDE: PHASE 3 TRANSFER PANEL ---
        tk.Label(self.right_frame, text="PHASE 3: URL TRANSFER", font=("Arial", 12, "bold"), bg="#f4f7f6").pack(pady=(0, 20))
        
        tk.Label(self.right_frame, text="Target Order ID:", bg="#f4f7f6", font=("Arial", 9, "bold")).pack(anchor="w")
        self.trans_oid_var = tk.StringVar(value="None Selected")
        tk.Label(self.right_frame, textvariable=self.trans_oid_var, fg="#2c3e50", font=("Arial", 11), bg="#f4f7f6").pack(anchor="w", pady=(0, 15))

        tk.Label(self.right_frame, text="Transfer URLs (One per line):", bg="#f4f7f6", font=("Arial", 9, "bold")).pack(anchor="w")
        self.url_box = tk.Text(self.right_frame, height=12, width=45, font=("Arial", 10))
        self.url_box.pack(pady=5, fill="x")

        self.btn_submit_transfer = tk.Button(
            self.right_frame, text="EXECUTE TRANSFER POST", command=self.execute_integrated_transfer, 
            bg="#bdc3c7", fg="white", font=("Arial", 10, "bold"), pady=15, state="disabled"
        )
        self.btn_submit_transfer.pack(fill="x", pady=20)
        
        self.write_log("Application Initialized. Use DUAL FETCH to begin.")

    def write_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.history_text.insert(tk.END, f"[{ts}] {msg}\n"); self.history_text.see(tk.END)

    def start_dual_fetch(self):
        if not self.api_token:
            messagebox.showerror("Error", ".env missing VIVID_API_TOKEN")
            return
        self.btn_fetch.config(state="disabled")
        threading.Thread(target=self.run_dual_sequence, daemon=True).start()

    def run_dual_sequence(self):
        combined_new_orders = []
        self.info_label.config(text="Fetching Shipment...", fg="orange")
        combined_new_orders.extend(self.fetch_api_logic("https://brokers.vividseats.com/webservices/v1/getOrders", {"apiToken": self.api_token, "status": "PENDING_SHIPMENT"}))
        
        self.info_label.config(text="Fetching Retransfer...", fg="orange")
        combined_new_orders.extend(self.fetch_api_logic("https://brokers.vividseats.com/webservices/v1/getPendingRetransferOrders", {"apiToken": self.api_token}))

        final_session_list = []
        for data in combined_new_orders:
            oid = data.get("orderId")
            if not any(d.get('orderId') == oid for d in self.phase1_results):
                self.phase1_results.append(data)
                final_session_list.append(data)
        
        self.auto_save_session(final_session_list)
        self.root.after(0, self.refresh_table_view)
        self.info_label.config(text="Enriching Data...", fg="blue")
        self.background_enrichment(self.api_token, final_session_list)
        
        time.sleep(5)
        self.root.after(0, lambda: self.btn_fetch.config(state="normal"))

    def fetch_api_logic(self, url, params):
        try:
            res = requests.get(url, params=params, headers={"Accept": "application/xml"}, timeout=30)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                return [{child.tag: (child.text.strip() if child.text else "") for child in o} for o in root.findall("order")]
        except Exception as e: self.write_log(f"Fetch Error: {e}")
        return []

    def background_enrichment(self, token, session_data):
        for order in session_data:
            oid = order.get("orderId")
            try:
                res = requests.get("https://brokers.vividseats.com/webservices/v1/getOrder", params={"apiToken": token, "orderId": oid}, headers={"Accept": "application/xml"}, timeout=15)
                if res.status_code == 200:
                    details = {child.tag: (child.text.strip() if child.text else "") for child in ET.fromstring(res.content)}
                    self.enriched_data[oid] = details
                    self.root.after(0, self.update_tree1_row, oid, details)
            except: pass
        self.root.after(0, lambda: self.info_label.config(text="Sync Complete", fg="green"))

    # --- PHASE 3 EXECUTION ---
    def execute_integrated_transfer(self):
        order_id = self.trans_oid_var.get()
        details = self.enriched_data.get(order_id)
        raw_text = self.url_box.get("1.0", tk.END).strip()
        url_list = [line.strip() for line in raw_text.splitlines() if line.strip()]
        
        if not url_list or not details: return

        # Construct payload matching url-encoded requirements
        payload = {
            "apiToken": self.api_token,
            "orderId": order_id,
            "orderToken": details.get('orderToken', ''),
            "transferURLList": url_list,
            "transferSource": "Manual_GUI_Automation",
            "transferSourceURL": url_list[0]
        }

        try:
            res = requests.post(
                "https://brokers.vividseats.com/webservices/v1/transferOrderViaURL", 
                data=payload, 
                headers={"Accept": "application/xml", "Content-Type": "application/x-www-form-urlencoded"}
            )
            root = ET.fromstring(res.content)
            success = root.findtext('success')
            msg = root.findtext('message') or "No response message"
            
            self.write_log(f"TRANSFER [{order_id}]: Success={success} | {msg}")
            messagebox.showinfo("Result", f"Transfer Success: {success}\n{msg}")
            if success == 'true': self.url_box.delete("1.0", tk.END)
        except Exception as e: self.write_log(f"POST Error: {e}")

    def on_order_selected(self, event):
        selected = self.tree1.selection()
        if not selected: return
        vals = self.tree1.item(selected[0])['values']
        oid = str(vals[0])
        self.trans_oid_var.set(oid)
        
        # Phase 3 Activation Check
        if vals[5] == "YES (URL)":
            self.btn_submit_transfer.config(state="normal", bg="#e67e22")
        else:
            self.btn_submit_transfer.config(state="disabled", bg="#bdc3c7")

        for item in self.tree2.get_children(): self.tree2.delete(item)
        details = self.enriched_data.get(oid) or next((i for i in self.phase1_results if str(i["orderId"]) == oid), None)
        if details:
            for k, v in sorted(details.items()): self.tree2.insert("", "end", values=(k, v))

    def refresh_table_view(self):
        for item in self.tree1.get_children(): self.tree1.delete(item)
        threshold = datetime.now() - timedelta(hours=12)
        for data in self.phase1_results:
            if self.hide_past_var.get():
                try:
                    if datetime.strptime(data.get("eventDate"), "%Y-%m-%d %H:%M:%S") < threshold: continue
                except: pass
            oid = data.get("orderId")
            is_url = "YES (URL)" if self.enriched_data.get(oid, {}).get('transferViaURL') == 'true' or data.get('transferViaURL') == 'true' else "No"
            self.tree1.insert("", "end", values=(oid, data.get("event"), data.get("eventDate"), data.get("quantity"), data.get("status"), is_url))
        self.auto_sort_by_date()

    def sort_column(self, col):
        l = [(self.tree1.set(k, col), k) for k in self.tree1.get_children('')]
        l.sort(reverse=self.sort_reverse); self.sort_reverse = not self.sort_reverse
        for index, (val, k) in enumerate(l): self.tree1.move(k, '', index)

    def auto_sort_by_date(self):
        items = [(self.tree1.set(k, "date"), k) for k in self.tree1.get_children('')]
        items.sort(key=lambda x: datetime.strptime(x[0], "%Y-%m-%d %H:%M:%S") if x[0] else datetime.max)
        for index, (val, k) in enumerate(items): self.tree1.move(k, '', index)

    def auto_load_existing_csvs(self):
        for file in glob.glob("*.csv"):
            try:
                with open(file, mode='r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        if row.get('orderId') and not any(d.get('orderId') == row.get('orderId') for d in self.phase1_results):
                            self.phase1_results.append(row)
                            if len(row) > 10: self.enriched_data[row['orderId']] = row
            except: pass
        self.refresh_table_view()

    def auto_save_session(self, data_list):
        if not data_list: return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        headers = sorted(list(set().union(*(d.keys() for d in data_list))))
        with open(f"Vivid_Batch_{ts}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader(); writer.writerows(data_list)

if __name__ == "__main__":
    main_root = tk.Tk()
    app = VividMasterApp(main_root)
    main_root.mainloop()
