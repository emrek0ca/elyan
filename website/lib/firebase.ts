import { initializeApp, getApps, getApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, OAuthProvider } from "firebase/auth";

const firebaseConfig = {
  apiKey: "AIzaSyB-KWLyvsZETeKDDirLS-O0Cw4RV4yCqXs",
  authDomain: "elyan-mobile.firebaseapp.com",
  projectId: "elyan-mobile",
  storageBucket: "elyan-mobile.firebasestorage.app",
  messagingSenderId: "762420924659",
  appId: "1:762420924659:web:44451554a083a1ace3a786",
  measurementId: "G-Z2PTPQ30M7"
};

// Initialize Firebase
const app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);
export const auth = getAuth(app);

export const googleProvider = new GoogleAuthProvider();
export const appleProvider = new OAuthProvider('apple.com');
appleProvider.addScope('email');
appleProvider.addScope('name');
