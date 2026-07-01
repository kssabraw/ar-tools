// Merged suite: the Fan-out app now shares the suite's single AuthProvider /
// auth context (mounted at the app root) instead of running its own. The suite's
// useAuth exposes a superset of what the Fan-out views consume
// ({ session, loading, signIn, signOut, ... }), so this re-export is drop-in.
export { useAuth } from "../../context/AuthContext";
