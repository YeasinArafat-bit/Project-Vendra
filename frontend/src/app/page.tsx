"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  MessageSquare, 
  ShoppingCart, 
  Package, 
  User, 
  Shield, 
  Send, 
  Image as ImageIcon, 
  Trash2, 
  ArrowRight, 
  Check, 
  X, 
  RefreshCw, 
  LogOut, 
  Info,
  DollarSign,
  AlertTriangle
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Product {
  id: string;
  name: string;
  price: number;
  description: string;
  image_url?: string;
  tags?: string[];
}

interface CartItem {
  product_id: string;
  name: string;
  size: string;
  quantity: number;
  price: number;
  subtotal: number;
}

interface Order {
  id: string;
  customer_id: string;
  items: any[];
  total: number;
  status: string;
  created_at: string;
}

interface RefundRequest {
  id: string;
  order_id: string;
  customer_id: string;
  requested_at: string;
  refund_type: string;
  eligibility_reason: string;
  status: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export default function Home() {
  // Screen views: 'auth' | 'app'
  const [view, setView] = useState<"auth" | "app">("auth");
  const [authTab, setAuthTab] = useState<"login" | "signup">("login");
  const [activeTab, setActiveTab] = useState<"chat" | "cart" | "orders" | "profile" | "admin">("chat");

  // Auth States
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [customerName, setCustomerName] = useState<string | null>(null);
  const [adminKey, setAdminKey] = useState("");
  const [isAdminAuthenticated, setIsAdminAuthenticated] = useState(false);

  // App States
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [activeCustomer, setActiveCustomer] = useState<any>(null);
  const [refundRequests, setRefundRequests] = useState<RefundRequest[]>([]);
  const [inventory, setInventory] = useState<Record<string, Record<string, number>>>({});
  const [productDetailsMap, setProductDetailsMap] = useState<Record<string, Product>>({});
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [selectedSizes, setSelectedSizes] = useState<Record<string, string>>({});
  const [modalSelectedSize, setModalSelectedSize] = useState<string>("");

  // Graph/Conversational states
  const [activeNode, setActiveNode] = useState("general");
  const [intent, setIntent] = useState("general");
  const [currentOrderId, setCurrentOrderId] = useState<string | null>(null);

  // Tracking codes & events cache
  const [trackingDetails, setTrackingDetails] = useState<Record<string, any>>({});

  // Loading/Pending states
  const [isPending, setIsPending] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load token on mount
  useEffect(() => {
    const savedToken = localStorage.getItem("vendra_token");
    const savedCustId = localStorage.getItem("vendra_customer_id");
    const savedCustName = localStorage.getItem("vendra_customer_name");
    const savedAdminKey = localStorage.getItem("vendra_admin_key");

    if (savedToken && savedCustId) {
      setToken(savedToken);
      setCustomerId(savedCustId);
      setCustomerName(savedCustName || "Customer");
      setView("app");
    }
    if (savedAdminKey) {
      setAdminKey(savedAdminKey);
      setIsAdminAuthenticated(true);
    }
  }, []);

  // Fetch initial app data on login/view-app switch
  useEffect(() => {
    if (view === "app" && token && customerId) {
      fetchCart();
      fetchOrders();
      fetchProfile();
      fetchInventory();
    }
  }, [view, token, customerId]);

  // Scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Alert dismiss
  useEffect(() => {
    if (errorMsg || successMsg) {
      const timer = setTimeout(() => {
        setErrorMsg(null);
        setSuccessMsg(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [errorMsg, successMsg]);

  useEffect(() => {
    if (selectedProduct) {
      const prodInventory = inventory[selectedProduct.id] || {};
      const availableSizes = Object.entries(prodInventory)
        .filter(([_, qty]) => qty > 0)
        .map(([sz]) => sz);
      setModalSelectedSize(availableSizes[0] || "");
    } else {
      setModalSelectedSize("");
    }
  }, [selectedProduct, inventory]);

  // Helper Headers
  const getAuthHeaders = (): Record<string, string> => {
    return token ? { "Authorization": `Bearer ${token}` } : {};
  };

  const getFullImageUrl = (url?: string) => {
    if (!url) return "";
    if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) {
      return url;
    }
    const cleanApiUrl = API_URL.endsWith("/") ? API_URL.slice(0, -1) : API_URL;
    const cleanUrl = url.startsWith("/") ? url : `/${url}`;
    return `${cleanApiUrl}${cleanUrl}`;
  };

  const getAdminHeaders = (): Record<string, string> => {
    return { "X-Admin-API-Key": adminKey };
  };

  // --- API CALLS ---

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return;
    setIsPending(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (res.ok) {
        setToken(data.token);
        setCustomerId(data.customer_id);
        setCustomerName(data.name);
        localStorage.setItem("vendra_token", data.token);
        localStorage.setItem("vendra_customer_id", data.customer_id);
        localStorage.setItem("vendra_customer_name", data.name);
        setView("app");
        setSuccessMsg(`Welcome back, ${data.name}!`);
      } else {
        setErrorMsg(data.detail || "Invalid login credentials.");
      }
    } catch (err) {
      setErrorMsg("Failed to connect to backend server.");
    } finally {
      setIsPending(false);
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || !name) return;
    setIsPending(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`${API_URL}/api/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, name, phone, address }),
      });
      const data = await res.json();
      if (res.ok) {
        setToken(data.token);
        setCustomerId(data.customer_id);
        setCustomerName(data.name);
        localStorage.setItem("vendra_token", data.token);
        localStorage.setItem("vendra_customer_id", data.customer_id);
        localStorage.setItem("vendra_customer_name", data.name);
        setView("app");
        setSuccessMsg(`Account created! Welcome, ${data.name}!`);
      } else {
        setErrorMsg(data.detail || "Signup failed.");
      }
    } catch (err) {
      setErrorMsg("Failed to connect to backend server.");
    } finally {
      setIsPending(false);
    }
  };

  const handleLogout = () => {
    setToken(null);
    setCustomerId(null);
    setCustomerName(null);
    localStorage.removeItem("vendra_token");
    localStorage.removeItem("vendra_customer_id");
    localStorage.removeItem("vendra_customer_name");
    setMessages([]);
    setView("auth");
  };

  const fetchCart = async () => {
    if (!customerId) return;
    try {
      const res = await fetch(`${API_URL}/api/cart/cart_${customerId}`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setCart(data.items || []);
        // Prefetch details of products currently in cart
        data.items?.forEach((item: CartItem) => {
          fetchProductDetails(item.product_id);
        });
      }
    } catch (err) {
      console.error("Error fetching cart:", err);
    }
  };

  const fetchOrders = async () => {
    if (!customerId) return;
    try {
      const res = await fetch(`${API_URL}/api/orders?customer_id=${customerId}`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setOrders(data.orders || []);
        // Fetch tracking for each paid/shipped order
        data.orders?.forEach((o: Order) => {
          fetchTracking(o.id);
        });
      }
    } catch (err) {
      console.error("Error fetching orders:", err);
    }
  };

  const fetchProfile = async () => {
    if (!customerId) return;
    try {
      const res = await fetch(`${API_URL}/api/customers/${customerId}`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setActiveCustomer(data);
      }
    } catch (err) {
      console.error("Error fetching profile:", err);
    }
  };

  const fetchInventory = async () => {
    try {
      const res = await fetch(`${API_URL}/api/inventory`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setInventory(data || {});
      }
    } catch (err) {
      console.error("Error fetching inventory:", err);
    }
  };

  const fetchProductDetails = async (productId: string) => {
    if (productDetailsMap[productId]) return;
    try {
      const res = await fetch(`${API_URL}/api/products/${productId}/details`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setProductDetailsMap(prev => ({ ...prev, [productId]: data }));
      }
    } catch (err) {
      console.error(`Error fetching details for ${productId}:`, err);
    }
  };

  const fetchTracking = async (orderId: string) => {
    if (trackingDetails[orderId]) return;
    try {
      const res = await fetch(`${API_URL}/api/orders/${orderId}/tracking`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const trackingData = await res.json();
        setTrackingDetails(prev => ({
          ...prev,
          [orderId]: trackingData
        }));
      }
    } catch (err) {
      console.error("Error fetching tracking:", err);
    }
  };

  const handleAddToCart = async (productId: string, size: string) => {
    if (!customerId) return;
    setIsPending(true);
    try {
      const res = await fetch(`${API_URL}/api/cart/cart_${customerId}/add`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders()
        },
        body: JSON.stringify({ product_id: productId, size, quantity: 1 }),
      });
      if (res.ok) {
        await fetchCart();
        setSuccessMsg("Product added to cart!");
        setActiveTab("cart");
      } else {
        const data = await res.json();
        setErrorMsg(data.detail || "Could not add item to cart.");
      }
    } catch (err) {
      setErrorMsg("Failed to connect to backend server.");
    } finally {
      setIsPending(false);
    }
  };

  const handleRemoveFromCart = async (productId: string) => {
    if (!customerId) return;
    setIsPending(true);
    try {
      const res = await fetch(`${API_URL}/api/cart/cart_${customerId}/remove?product_id=${productId}`, {
        method: "POST",
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        await fetchCart();
        setSuccessMsg("Item removed from cart.");
      } else {
        const data = await res.json();
        setErrorMsg(data.detail || "Could not remove item.");
      }
    } catch (err) {
      setErrorMsg("Failed to connect to backend.");
    } finally {
      setIsPending(false);
    }
  };

  const handleSimulatePayment = async (orderId: string) => {
    setIsPending(true);
    try {
      const res = await fetch(`${API_URL}/webhook/stripe`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders()
        },
        body: JSON.stringify({
          order_id: orderId,
          stripe_event_id: `evt_mock_nextjs_${orderId}`,
          mock: true
        }),
      });
      if (res.ok) {
        setSuccessMsg(`Simulated payment successful! Order #${orderId} marked as PAID.`);
        await fetchOrders();
      } else {
        const data = await res.json();
        setErrorMsg(data.detail || "Stripe mock payment declined.");
      }
    } catch (err) {
      setErrorMsg("Failed to process payment webhook.");
    } finally {
      setIsPending(false);
    }
  };

  // Convert files to base64
  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        const result = reader.result as string;
        // Strip data:image/*;base64, prefix
        const base64Data = result.split(",")[1];
        resolve(base64Data);
      };
      reader.onerror = error => reject(error);
    });
  };

  const handleSendChatMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!chatInput.trim() && !selectedImage) return;

    const userText = chatInput.trim();
    const currentMessages = [...messages];
    
    // Add user message locally
    const newUserMsg: ChatMessage = { role: "user", content: userText || "[Photo Uploaded]" };
    setMessages(prev => [...prev, newUserMsg]);
    setChatInput("");
    setIsPending(true);

    try {
      let imageB64: string | null = null;
      if (selectedImage) {
        imageB64 = await fileToBase64(selectedImage);
        setSelectedImage(null);
      }

      // Serialize history
      const history = currentMessages.map(m => ({
        role: m.role,
        content: m.content
      }));

      const payload = {
        message: userText,
        history: history,
        customer_id: customerId,
        image_bytes: imageB64,
        active_node: activeNode,
        intent: intent,
        current_order_id: currentOrderId
      };

      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders()
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const data = await res.json();
        // Backend returns all messages, take the final assistant reply
        const returnedMsgs = data.messages || [];
        const finalAssistantMsg = returnedMsgs[returnedMsgs.length - 1];
        if (finalAssistantMsg) {
          setMessages(prev => [...prev, { role: "assistant", content: finalAssistantMsg.content }]);
          // Parse product IDs out of the content to pre-cache product card visuals
          const productMatches = finalAssistantMsg.content.match(/P\d{3}/g);
          if (productMatches) {
            productMatches.forEach((pid: string) => fetchProductDetails(pid));
          }
        }
        
        setActiveNode(data.active_node || "general");
        setIntent(data.intent || "general");
        setCurrentOrderId(data.current_order_id || null);

        // Auto-refresh states if intent triggers changes
        if (data.intent === "checkout" || data.intent === "cart") {
          fetchCart();
        }
        if (data.intent === "order_tracking" || data.intent === "refund") {
          fetchOrders();
        }
      } else {
        const errText = await res.text();
        setErrorMsg(`Failed to chat: ${errText}`);
      }
    } catch (err) {
      setErrorMsg("Failed to connect to backend server.");
    } finally {
      setIsPending(false);
    }
  };

  // --- ADMIN PANEL HANDLERS ---

  const handleAdminVerify = (e: React.FormEvent) => {
    e.preventDefault();
    if (!adminKey.trim()) return;
    localStorage.setItem("vendra_admin_key", adminKey);
    setIsAdminAuthenticated(true);
    fetchPendingRefunds();
  };

  const handleAdminLogout = () => {
    setIsAdminAuthenticated(false);
    setRefundRequests([]);
    localStorage.removeItem("vendra_admin_key");
  };

  const fetchPendingRefunds = async () => {
    if (!adminKey) return;
    setIsPending(true);
    try {
      const res = await fetch(`${API_URL}/api/refunds/pending`, {
        headers: getAdminHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setRefundRequests(data || []);
      } else {
        const errText = await res.text();
        setErrorMsg(`Admin authorization failed: ${errText}`);
        setIsAdminAuthenticated(false);
      }
    } catch (err) {
      setErrorMsg("Failed to fetch pending refunds.");
    } finally {
      setIsPending(false);
    }
  };

  const handleApproveRefund = async (requestId: string) => {
    setIsPending(true);
    try {
      const res = await fetch(`${API_URL}/api/refunds/${requestId}/approve`, {
        method: "POST",
        headers: getAdminHeaders(),
      });
      if (res.ok) {
        setSuccessMsg(`Refund request #${requestId} approved.`);
        await fetchPendingRefunds();
        await fetchOrders();
      } else {
        const errText = await res.text();
        setErrorMsg(`Approval failed: ${errText}`);
      }
    } catch (err) {
      setErrorMsg("Failed to approve refund.");
    } finally {
      setIsPending(false);
    }
  };

  const handleDenyRefund = async (requestId: string) => {
    setIsPending(true);
    try {
      const res = await fetch(`${API_URL}/api/refunds/${requestId}/deny?review_notes=Rejected via Next.js panel`, {
        method: "POST",
        headers: getAdminHeaders(),
      });
      if (res.ok) {
        setSuccessMsg(`Refund request #${requestId} denied.`);
        await fetchPendingRefunds();
        await fetchOrders();
      } else {
        const errText = await res.text();
        setErrorMsg(`Denial failed: ${errText}`);
      }
    } catch (err) {
      setErrorMsg("Failed to deny refund.");
    } finally {
      setIsPending(false);
    }
  };

  // Safe formatting helper for currency
  const formatBDT = (amount: number) => {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "BDT", minimumFractionDigits: 1 }).format(amount).replace("BDT", "৳");
  };

  // Find mentioned product IDs in chat reply
  const getProductCardsForMessage = (content: string) => {
    const matches = content.match(/P\d{3}/g);
    if (!matches) return [];
    const uniqueIds = Array.from(new Set(matches));
    return uniqueIds.map(id => productDetailsMap[id]).filter(Boolean);
  };

  // --- SCREEN RENDERS ---

  if (view === "auth") {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        {/* Error/Success Alert floating */}
        {errorMsg && (
          <div className="fixed top-4 left-4 right-4 z-50 rounded-lg bg-red-900/90 p-4 border border-red-500 text-red-200 shadow-lg text-sm flex items-center md:left-auto md:w-96">
            <AlertTriangle className="mr-2 h-5 w-5 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900/80 p-8 shadow-2xl backdrop-blur-xl">
          <div className="mb-8 text-center">
            <h1 className="bg-gradient-to-r from-blue-400 via-indigo-400 to-violet-400 bg-clip-text text-4xl font-extrabold text-transparent">
              VENDRA
            </h1>
            <p className="mt-2 text-sm text-slate-400">Conversational Footwear Assistant</p>
          </div>

          <div className="mb-6 flex border-b border-slate-800">
            <button
              onClick={() => { setAuthTab("login"); setErrorMsg(null); }}
              className={`flex-1 pb-3 text-center font-semibold text-sm transition-colors ${
                authTab === "login" 
                  ? "border-b-2 border-indigo-500 text-indigo-400" 
                  : "text-slate-500 hover:text-slate-400"
              }`}
            >
              Sign In
            </button>
            <button
              onClick={() => { setAuthTab("signup"); setErrorMsg(null); }}
              className={`flex-1 pb-3 text-center font-semibold text-sm transition-colors ${
                authTab === "signup" 
                  ? "border-b-2 border-indigo-500 text-indigo-400" 
                  : "text-slate-500 hover:text-slate-400"
              }`}
            >
              Create Account
            </button>
          </div>

          {authTab === "login" ? (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Email Address</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                  placeholder="name@domain.com"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Password</label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                  placeholder="••••••••"
                />
              </div>
              <button
                type="submit"
                disabled={isPending}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 p-3 font-semibold text-white shadow-lg hover:from-blue-500 hover:to-indigo-500 active:scale-[0.98] transition-all disabled:opacity-50 disabled:pointer-events-none"
              >
                {isPending ? <RefreshCw className="h-5 w-5 animate-spin" /> : "Sign In"}
                <ArrowRight className="h-4 w-4" />
              </button>
            </form>
          ) : (
            <form onSubmit={handleSignup} className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Full Name</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                  placeholder="Alice Johnson"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Email Address</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                  placeholder="name@domain.com"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Password</label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                  placeholder="Min. 8 characters"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Phone (Optional)</label>
                <input
                  type="text"
                  value={phone}
                  onChange={e => setPhone(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                  placeholder="017xxxxxxxx"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Address (Optional)</label>
                <input
                  type="text"
                  value={address}
                  onChange={e => setAddress(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                  placeholder="Delivery Address"
                />
              </div>
              <button
                type="submit"
                disabled={isPending}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 p-3 font-semibold text-white shadow-lg hover:from-indigo-500 hover:to-violet-500 active:scale-[0.98] transition-all disabled:opacity-50 disabled:pointer-events-none"
              >
                {isPending ? <RefreshCw className="h-5 w-5 animate-spin" /> : "Register"}
                <ArrowRight className="h-4 w-4" />
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  // APP VIEW
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Dynamic Floating Alerts */}
      {errorMsg && (
        <div className="fixed top-4 right-4 z-50 rounded-xl bg-red-950/90 border border-red-800 p-4 text-red-200 shadow-xl text-xs flex items-center w-80 animate-bounce">
          <AlertTriangle className="mr-2 h-4 w-4 text-red-400" />
          <span>{errorMsg}</span>
        </div>
      )}
      {successMsg && (
        <div className="fixed top-4 right-4 z-50 rounded-xl bg-emerald-950/90 border border-emerald-800 p-4 text-emerald-200 shadow-xl text-xs flex items-center w-80">
          <Check className="mr-2 h-4 w-4 text-emerald-400" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* TOP HEADER */}
      <header className="flex h-16 items-center justify-between border-b border-slate-800 bg-slate-950/75 px-6 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <span className="bg-gradient-to-r from-blue-400 via-indigo-400 to-violet-400 bg-clip-text text-xl font-extrabold tracking-wider text-transparent">
            VENDRA
          </span>
          <span className="hidden rounded-full bg-slate-800/80 px-2 py-0.5 text-[10px] font-bold text-slate-400 md:inline-block border border-slate-700">
            Node: {activeNode}
          </span>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-400">
            Welcome, <strong className="text-slate-200">{customerName}</strong> ({customerId})
          </span>
          <button 
            onClick={handleLogout}
            className="flex items-center justify-center p-2 rounded-xl bg-slate-800/50 hover:bg-red-950/50 text-slate-400 hover:text-red-300 border border-slate-700/50 transition-colors"
            title="Log Out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* MAIN CONTAINER: DUAL PANE */}
      <div className="flex flex-1 overflow-hidden">
        
        {/* LEFT PANE: CONVERSATIONAL CHAT WORKSPACE */}
        <div className="flex w-full flex-col border-r border-slate-800 bg-slate-950/30 md:w-3/5 lg:w-1/2">
          {/* Conversational Screen */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center p-8 space-y-4">
                <div className="p-4 rounded-full bg-indigo-600/10 border border-indigo-500/20 text-indigo-400 animate-pulse">
                  <MessageSquare className="h-10 w-10" />
                </div>
                <h3 className="text-lg font-bold text-slate-200">Hi, I'm Vendra!</h3>
                <p className="text-xs text-slate-400 max-w-sm">
                  I can help you browse shoes, manage your cart, track live orders, or submit cancellations/refunds.
                </p>
                <div className="grid grid-cols-2 gap-2 max-w-xs mt-2">
                  <button 
                    onClick={() => { setChatInput("Show me premium running shoes"); }}
                    className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-[10px] text-slate-400 hover:bg-slate-800 transition-colors"
                  >
                    "Show me running shoes"
                  </button>
                  <button 
                    onClick={() => { setChatInput("What is the return policy?"); }}
                    className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-[10px] text-slate-400 hover:bg-slate-800 transition-colors"
                  >
                    "Check return policy"
                  </button>
                </div>
              </div>
            ) : (
              messages.map((m, idx) => (
                <div key={idx} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
                  <div className={`max-w-[85%] rounded-2xl p-4 text-sm ${
                    m.role === "user" 
                      ? "bg-indigo-600/90 text-white rounded-br-none border border-indigo-500/50" 
                      : "bg-slate-900/90 text-slate-100 rounded-bl-none border border-slate-800/80 shadow-md"
                  }`}>
                    {/* Safe text format mapping */}
                    <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
                  </div>

                  {/* Render Product Cards for recommendations directly below bubbles */}
                  {m.role === "assistant" && getProductCardsForMessage(m.content).length > 0 && (
                    <div className="grid grid-cols-1 gap-4 mt-3 w-full sm:grid-cols-2 max-w-[90%]">
                      {getProductCardsForMessage(m.content).map((prod) => {
                        const prodInventory = inventory[prod.id] || {};
                        const availableSizes = Object.entries(prodInventory)
                          .filter(([_, qty]) => qty > 0)
                          .map(([sz]) => sz);
                        const currentSelectedSize = selectedSizes[prod.id] || availableSizes[0] || "";

                        return (
                          <div key={prod.id} className="group overflow-hidden rounded-xl border border-slate-800 bg-slate-950/60 p-4 shadow-lg hover:border-indigo-500/40 hover:bg-slate-950 transition-all duration-300">
                            {prod.image_url ? (
                              <img src={getFullImageUrl(prod.image_url)} alt={prod.name} className="h-28 w-full rounded-lg object-cover mb-3 group-hover:scale-[1.03] transition-transform duration-300" />
                            ) : (
                              <div className="h-28 w-full bg-slate-900 rounded-lg flex items-center justify-center text-slate-600 text-xs mb-3">No Image</div>
                            )}
                            <div className="flex items-start justify-between">
                              <h4 className="font-bold text-slate-200 text-xs truncate group-hover:text-indigo-400 transition-colors">{prod.name}</h4>
                              <span className="text-xs font-bold text-indigo-400">{formatBDT(prod.price)}</span>
                            </div>
                            <p className="text-[10px] text-slate-500 mt-1 line-clamp-2 h-7">{prod.description}</p>
                            
                            {/* Size Dropdown */}
                            <div className="mt-2 flex items-center justify-between gap-1.5 text-[11px]">
                              <span className="text-slate-500 font-medium">Size:</span>
                              <select
                                value={currentSelectedSize}
                                onChange={(e) => setSelectedSizes(prev => ({ ...prev, [prod.id]: e.target.value }))}
                                className="bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 flex-1 min-w-0"
                              >
                                {Object.keys(prodInventory).length === 0 ? (
                                  <option value="">No stock data</option>
                                ) : (
                                  Object.entries(prodInventory).map(([sz, qty]) => (
                                    <option key={sz} value={sz} disabled={qty <= 0}>
                                      {sz} {qty <= 0 ? "(Out of stock)" : `(${qty} left)`}
                                    </option>
                                  ))
                                )}
                              </select>
                            </div>

                            <div className="flex gap-2 mt-3">
                              <button
                                disabled={!currentSelectedSize}
                                onClick={() => {
                                  if (currentSelectedSize) {
                                    handleAddToCart(prod.id, currentSelectedSize);
                                  } else {
                                    setErrorMsg("Please select an in-stock size.");
                                  }
                                }}
                                className="flex-1 text-[10px] bg-indigo-600 hover:bg-indigo-500 font-semibold p-1.5 rounded-lg text-white shadow transition-colors disabled:opacity-50"
                              >
                                🛒 Add to Cart
                              </button>
                              <button
                                onClick={() => setSelectedProduct(prod)}
                                className="p-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-slate-400 text-xs flex items-center justify-center"
                                title="Product Info"
                              >
                                <Info className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* CHAT INPUT AREA */}
          <form onSubmit={handleSendChatMessage} className="border-t border-slate-800/80 bg-slate-950/40 p-4">
            <div className="flex items-center gap-2">
              <label 
                className={`flex items-center justify-center p-3 rounded-xl border border-slate-700 cursor-pointer transition-colors ${
                  selectedImage ? "bg-indigo-950/60 text-indigo-400 border-indigo-500" : "bg-slate-900 hover:bg-slate-800 text-slate-400"
                }`}
                title="Upload image for Visual Search (CLIP)"
              >
                <ImageIcon className="h-5 w-5" />
                <input
                  type="file"
                  accept="image/*"
                  onChange={e => setSelectedImage(e.target.files?.[0] || null)}
                  className="hidden"
                />
              </label>

              <input
                type="text"
                maxLength={3000}
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                placeholder={selectedImage ? "Image selected. Press Send or write description..." : "Ask Vendra to browse, check tracking, or request refund..."}
                className="flex-1 rounded-xl border border-slate-700 bg-slate-900 p-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
              />

              <button
                type="submit"
                disabled={isPending || (!chatInput.trim() && !selectedImage)}
                className="flex items-center justify-center p-3 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 text-white hover:from-blue-500 hover:to-indigo-500 active:scale-[0.98] transition-all disabled:opacity-50 disabled:pointer-events-none shadow-lg"
              >
                {isPending ? <RefreshCw className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
              </button>
            </div>
            {selectedImage && (
              <div className="mt-2 text-[10px] text-indigo-400 flex items-center justify-between bg-indigo-950/40 p-2 rounded-lg border border-indigo-900/60">
                <span className="truncate">📎 Selected: {selectedImage.name}</span>
                <button onClick={() => setSelectedImage(null)} className="text-red-400 hover:text-red-300">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </form>
        </div>

        {/* RIGHT PANE: CART, ORDERS, PROFILE, ADMIN CONTROLS */}
        <div className="hidden flex-col bg-slate-950/15 md:flex md:w-2/5 lg:w-1/2">
          {/* Tabs Bar */}
          <div className="flex border-b border-slate-800 bg-slate-950/40 p-2">
            <button
              onClick={() => setActiveTab("chat")}
              className={`flex flex-1 items-center justify-center gap-1.5 py-3 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                activeTab === "chat" 
                  ? "bg-slate-900 border border-slate-700 text-indigo-400" 
                  : "text-slate-400 hover:text-slate-300"
              }`}
            >
              <MessageSquare className="h-4 w-4" />
              Chat
            </button>
            <button
              onClick={() => setActiveTab("cart")}
              className={`flex flex-1 items-center justify-center gap-1.5 py-3 rounded-xl text-xs font-semibold tracking-wide transition-all relative ${
                activeTab === "cart" 
                  ? "bg-slate-900 border border-slate-700 text-indigo-400" 
                  : "text-slate-400 hover:text-slate-300"
              }`}
            >
              <ShoppingCart className="h-4 w-4" />
              Cart
              {cart.length > 0 && (
                <span className="absolute top-1 right-2 flex h-5 w-5 items-center justify-center rounded-full bg-indigo-500 text-[10px] font-bold text-white border border-slate-950">
                  {cart.reduce((sum, item) => sum + item.quantity, 0)}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("orders")}
              className={`flex flex-1 items-center justify-center gap-1.5 py-3 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                activeTab === "orders" 
                  ? "bg-slate-900 border border-slate-700 text-indigo-400" 
                  : "text-slate-400 hover:text-slate-300"
              }`}
            >
              <Package className="h-4 w-4" />
              Orders
            </button>
            <button
              onClick={() => setActiveTab("profile")}
              className={`flex flex-1 items-center justify-center gap-1.5 py-3 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                activeTab === "profile" 
                  ? "bg-slate-900 border border-slate-700 text-indigo-400" 
                  : "text-slate-400 hover:text-slate-300"
              }`}
            >
              <User className="h-4 w-4" />
              Profile
            </button>
            <button
              onClick={() => setActiveTab("admin")}
              className={`flex flex-1 items-center justify-center gap-1.5 py-3 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                activeTab === "admin" 
                  ? "bg-slate-900 border border-slate-700 text-indigo-400" 
                  : "text-slate-400 hover:text-slate-300"
              }`}
            >
              <Shield className="h-4 w-4" />
              Admin
            </button>
          </div>

          {/* TAB CONTENTS CONTAINER */}
          <div className="flex-1 overflow-y-auto p-6">
            
            {/* CART TAB */}
            {activeTab === "cart" && (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold text-slate-200">Your Cart</h3>
                  <button 
                    onClick={fetchCart} 
                    className="p-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-800 transition-colors"
                  >
                    <RefreshCw className="h-4 w-4" />
                  </button>
                </div>

                {cart.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center text-slate-500 border border-dashed border-slate-800 rounded-xl bg-slate-900/10">
                    <ShoppingCart className="h-8 w-8 mb-2 opacity-50" />
                    <p className="text-xs">Your shopping cart is currently empty.</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {cart.map((item, idx) => {
                      const details = productDetailsMap[item.product_id];
                      return (
                        <div key={idx} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                          <div className="flex items-center gap-3">
                            {details?.image_url ? (
                              <img src={getFullImageUrl(details.image_url)} alt={item.name} className="h-14 w-14 rounded-lg object-cover" />
                            ) : (
                              <div className="h-14 w-14 bg-slate-800 rounded-lg flex items-center justify-center text-[10px] text-slate-500">No Image</div>
                            )}
                            <div>
                              <h4 className="font-bold text-slate-200 text-sm">{details?.name || item.name}</h4>
                              <p className="text-xs text-slate-500 mt-0.5">Size: {item.size} | Qty: {item.quantity}</p>
                            </div>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className="font-bold text-indigo-400 text-sm">{formatBDT(item.subtotal)}</span>
                            <button
                              onClick={() => handleRemoveFromCart(item.product_id)}
                              className="text-red-400 hover:text-red-300 p-2 rounded-lg hover:bg-red-950/20"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                      );
                    })}

                    <div className="rounded-xl border border-slate-800 bg-slate-950 p-6 space-y-4">
                      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                        <span className="text-xs text-slate-400 uppercase tracking-wider font-semibold">Subtotal</span>
                        <strong className="text-indigo-400 text-lg">
                          {formatBDT(cart.reduce((sum, item) => sum + item.subtotal, 0))}
                        </strong>
                      </div>
                      <p className="text-[10px] text-slate-500">
                        Ask Vendra to "checkout my cart" in the chat pane to generate an order and checkout link.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ORDERS TAB */}
            {activeTab === "orders" && (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold text-slate-200">Your Orders</h3>
                  <button 
                    onClick={fetchOrders} 
                    className="p-2 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-800 transition-colors"
                  >
                    <RefreshCw className="h-4 w-4" />
                  </button>
                </div>

                {orders.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center text-slate-500 border border-dashed border-slate-800 rounded-xl bg-slate-900/10">
                    <Package className="h-8 w-8 mb-2 opacity-50" />
                    <p className="text-xs">No orders recorded for your profile.</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {orders.map((o) => {
                      const tracking = trackingDetails[o.id];
                      return (
                        <div key={o.id} className="rounded-xl border border-slate-800 bg-slate-900/30 p-5 space-y-4">
                          <div className="flex items-center justify-between">
                            <div>
                              <strong className="text-slate-200 text-sm">Order #{o.id}</strong>
                              <span className="text-[10px] text-slate-500 block mt-0.5">Placed on: {new Date(o.created_at).toLocaleDateString()}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
                                o.status === "paid" 
                                  ? "bg-emerald-950/60 text-emerald-400 border-emerald-800" 
                                  : o.status === "pending_payment" 
                                  ? "bg-amber-950/60 text-amber-400 border-amber-800" 
                                  : "bg-red-950/60 text-red-400 border-red-800"
                              }`}>
                                {o.status}
                              </span>
                              <strong className="text-indigo-400 text-sm">{formatBDT(o.total)}</strong>
                            </div>
                          </div>

                          {/* Action Button: Pay simulated Stripe */}
                          {o.status === "pending_payment" && (
                            <button
                              onClick={() => handleSimulatePayment(o.id)}
                              className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 p-2.5 text-xs font-semibold text-white transition-colors"
                            >
                              <DollarSign className="h-4 w-4" />
                              Simulate Stripe Payment Check (Mock)
                            </button>
                          )}

                          {/* Tracking timeline nested */}
                          {tracking && (
                            <div className="mt-2 rounded-lg bg-slate-950/80 p-4 border border-slate-950">
                              <div className="flex justify-between items-center mb-3">
                                <span className="text-xs font-semibold text-indigo-400">Tracking: {tracking.tracking_code}</span>
                                <span className="text-[10px] text-slate-400">Courier: {tracking.courier}</span>
                              </div>
                              <div className="space-y-3">
                                {tracking.timeline?.map((evt: any, eidx: number) => (
                                  <div key={eidx} className="flex gap-2.5">
                                    <div className="flex flex-col items-center">
                                      <div className="h-2 w-2 rounded-full bg-indigo-500 mt-1.5" />
                                      {eidx < tracking.timeline.length - 1 && <div className="w-0.5 bg-slate-800 flex-1 my-1" />}
                                    </div>
                                    <div>
                                      <strong className="text-xs text-slate-200 font-bold block">{evt.event || evt.status}</strong>
                                      <span className="text-[10px] text-slate-500 block">
                                        {evt.time ? new Date(evt.time).toLocaleString() : evt.note}
                                      </span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* PROFILE TAB */}
            {activeTab === "profile" && activeCustomer && (
              <div className="space-y-6">
                <h3 className="text-lg font-bold text-slate-200">Customer Profile</h3>
                <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-6 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block">Customer ID</span>
                      <strong className="text-slate-200 text-sm block mt-0.5">{activeCustomer.id}</strong>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block">Store Credit</span>
                      <strong className="text-indigo-400 text-sm block mt-0.5">{formatBDT(activeCustomer.store_credit || 0.0)}</strong>
                    </div>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block">Name</span>
                    <strong className="text-slate-200 text-sm block mt-0.5">{activeCustomer.name}</strong>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block">Email Address</span>
                    <strong className="text-slate-200 text-sm block mt-0.5">{activeCustomer.email}</strong>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block">Phone</span>
                    <strong className="text-slate-200 text-sm block mt-0.5">{activeCustomer.phone || "Not Set"}</strong>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block">Delivery Address</span>
                    <strong className="text-slate-200 text-sm block mt-0.5">{activeCustomer.address || "Not Set"}</strong>
                  </div>
                </div>
              </div>
            )}

            {/* ADMIN TAB */}
            {activeTab === "admin" && (
              <div className="space-y-6">
                <h3 className="text-lg font-bold text-slate-200">Admin Controls</h3>

                {!isAdminAuthenticated ? (
                  <form onSubmit={handleAdminVerify} className="rounded-xl border border-slate-800 bg-slate-900/30 p-6 space-y-4">
                    <p className="text-xs text-slate-400">
                      Enter the server `ADMIN_API_KEY` to authenticate as store administrator and review pending refund/cancellation requests.
                    </p>
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Admin API Key</label>
                      <input
                        type="password"
                        required
                        value={adminKey}
                        onChange={e => setAdminKey(e.target.value)}
                        className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
                        placeholder="vendra_admin_secret_key"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={isPending}
                      className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 p-3 font-semibold text-white shadow-lg hover:from-violet-500 hover:to-indigo-500 active:scale-[0.98] transition-all"
                    >
                      Authenticate Admin
                    </button>
                  </form>
                ) : (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div>
                        <strong className="text-xs text-emerald-400 block font-bold uppercase tracking-wider">Admin Authorized</strong>
                        <span className="text-[10px] text-slate-500 block">Action keys active.</span>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={fetchPendingRefunds}
                          className="p-2 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-400 transition-colors"
                          title="Refresh Queue"
                        >
                          <RefreshCw className="h-4 w-4" />
                        </button>
                        <button
                          onClick={handleAdminLogout}
                          className="p-2 rounded-lg bg-red-950/20 hover:bg-red-950/50 border border-red-900/40 text-red-400 transition-colors"
                          title="Lock Session"
                        >
                          <LogOut className="h-4 w-4" />
                        </button>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <h4 className="text-xs uppercase font-semibold text-slate-400 tracking-wider">Pending Refund Queue</h4>
                      {refundRequests.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-12 text-center text-slate-500 border border-dashed border-slate-800 rounded-xl bg-slate-900/10">
                          <Check className="h-8 w-8 mb-2 text-slate-600" />
                          <p className="text-xs">Queue is currently clear. No pending refund requests.</p>
                        </div>
                      ) : (
                        refundRequests.map((req) => (
                          <div key={req.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-5 space-y-4">
                            <div className="flex justify-between items-start">
                              <div>
                                <span className="text-xs font-semibold text-indigo-400 block">Request #{req.id}</span>
                                <span className="text-[10px] text-slate-400 mt-1 block">Customer: {req.customer_id} | Order: #{req.order_id}</span>
                              </div>
                              <span className="text-[10px] font-bold uppercase tracking-wider bg-amber-950/60 text-amber-400 border border-amber-800 px-2 py-0.5 rounded-full">
                                {req.refund_type === "store_credit" ? "Store Credit" : "Full Refund"}
                              </span>
                            </div>
                            <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-900/60 text-xs">
                              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 block mb-1">Reason for request:</span>
                              <p className="text-slate-300 italic">"{req.eligibility_reason}"</p>
                            </div>
                            <div className="flex gap-3">
                              <button
                                onClick={() => handleApproveRefund(req.id)}
                                className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 p-2.5 text-xs font-bold text-white transition-colors"
                              >
                                <Check className="h-4 w-4" />
                                Approve Refund
                              </button>
                              <button
                                onClick={() => handleDenyRefund(req.id)}
                                className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-red-950/40 hover:bg-red-950/80 border border-red-900/60 p-2.5 text-xs font-bold text-red-200 transition-colors"
                              >
                                <X className="h-4 w-4" />
                                Deny Request
                              </button>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

          </div>
        </div>

      </div>

      {/* PRODUCT DETAILS MODAL OVERLAY */}
      {selectedProduct && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-start border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-lg font-extrabold text-slate-100">{selectedProduct.name}</h3>
                <span className="text-[10px] text-slate-500 mt-1 block">Product ID: {selectedProduct.id}</span>
              </div>
              <button 
                onClick={() => setSelectedProduct(null)}
                className="p-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-300 transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            {selectedProduct.image_url ? (
              <img src={getFullImageUrl(selectedProduct.image_url)} alt={selectedProduct.name} className="h-56 w-full rounded-xl object-cover" />
            ) : (
              <div className="h-56 w-full bg-slate-950 rounded-xl flex items-center justify-center text-slate-500 text-xs">No Image Available</div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="text-[10px] uppercase font-bold text-slate-500 block">Retail Price</span>
                <strong className="text-indigo-400 text-lg block mt-0.5">{formatBDT(selectedProduct.price)}</strong>
              </div>
              <div>
                <span className="text-[10px] uppercase font-bold text-slate-500 block">Category Tags</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {selectedProduct.tags?.map((t, idx) => (
                    <span key={idx} className="text-[9px] bg-slate-800 px-2 py-0.5 rounded border border-slate-700 text-slate-400 font-semibold">{t}</span>
                  )) || <span className="text-[9px] text-slate-600 italic">None</span>}
                </div>
              </div>
            </div>

            <div>
              <span className="text-[10px] uppercase font-bold text-slate-500 block mb-1">Product Description</span>
              <p className="text-xs text-slate-300 leading-relaxed bg-slate-950/40 p-3 rounded-lg border border-slate-950">{selectedProduct.description}</p>
            </div>

            <div>
              <span className="text-[10px] uppercase font-bold text-slate-500 block mb-2">Select Size</span>
              <div className="flex flex-wrap gap-2">
                {Object.keys(inventory[selectedProduct.id] || {}).length === 0 ? (
                  <span className="text-xs text-slate-500 italic">No stock data available</span>
                ) : (
                  Object.entries(inventory[selectedProduct.id] || {}).map(([sz, qty]) => {
                    const isOutOfStock = qty <= 0;
                    const isSelected = modalSelectedSize === sz;
                    return (
                      <button
                        key={sz}
                        disabled={isOutOfStock}
                        onClick={() => setModalSelectedSize(sz)}
                        className={`px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
                          isOutOfStock 
                            ? "bg-slate-900 border-slate-800 text-slate-600 opacity-40 cursor-not-allowed line-through" 
                            : isSelected
                              ? "bg-indigo-600 border-indigo-500 text-white shadow-md shadow-indigo-600/30"
                              : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                        }`}
                      >
                        Size {sz} {isOutOfStock ? "(0)" : `(${qty})`}
                      </button>
                    );
                  })
                )}
              </div>
            </div>

            <div className="flex gap-3">
              <button
                disabled={!modalSelectedSize}
                onClick={() => {
                  if (modalSelectedSize) {
                    handleAddToCart(selectedProduct.id, modalSelectedSize);
                    setSelectedProduct(null);
                  }
                }}
                className="flex-1 rounded-xl bg-indigo-600 hover:bg-indigo-500 p-3 text-xs font-bold text-white transition-colors disabled:opacity-50 disabled:pointer-events-none"
              >
                🛒 Add {modalSelectedSize ? `Size ${modalSelectedSize}` : ""} to Cart
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
