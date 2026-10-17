
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js";

import {
    getAuth,
    createUserWithEmailAndPassword,
    signInWithEmailAndPassword,
    sendEmailVerification,
    browserLocalPersistence,
    setPersistence,
} from "https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js";

const firebaseConfig = {
    apiKey: "AIzaSyDpl1NtU2lyyvwalnfWQkWaLnHSRovUhBA",
    authDomain: "hcibs-sj-passdown.firebaseapp.com",
    projectId: "hcibs-sj-passdown",
    storageBucket: "hcibs-sj-passdown.firebasestorage.app",
    messagingSenderId: "1022703955351",
    appId: "1:1022703955351:web:f4cdec8233234064dae8d2",
    measurementId: "G-QPKLEWN6KP",
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

function showStatus(element, message) {
    if (element) element.textContent = message;
}

function getCsrfToken(form) {
    return (
        form?.querySelector('[name="csrfmiddlewaretoken"]')?.value ||
        document.querySelector('meta[name="csrf-token"]')?.content ||
        ""
    );
}

async function readResponse(response) {
    try {
        return await response.json();
    } catch {
        throw new Error(
            "The server returned an invalid response. Please try again."
        );
    }
}

// --------------------------------------------------
// COMPLETE DJANGO REGISTRATION
// --------------------------------------------------

async function completeDjangoRegistration({
    user,
    username,
    endpoint,
    csrfToken,
    status,
}) {
    await user.reload();

    if (!user.emailVerified) {
        showStatus(
            status,
            "Your email is not verified yet. Open the verification email first."
        );
        return false;
    }

    const idToken = await user.getIdToken(true);

    const response = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({
            id_token: idToken,
            username,
        }),
    });

    const data = await readResponse(response);

    if (!response.ok) {
        throw new Error(data.error || "Could not complete registration.");
    }

    sessionStorage.removeItem("sjpassdown_pending_username");
    window.location.assign(data.redirect || "/");

    return true;
}

// --------------------------------------------------
// REGISTRATION
// --------------------------------------------------

const registerForm = document.querySelector("[data-firebase-register]");

if (registerForm) {
    registerForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const status = registerForm.querySelector("[data-firebase-status]");
        const submitButton = registerForm.querySelector(
            'button[type="submit"]'
        );

        const username = registerForm.querySelector('[name="username"]')
            ?.value.trim();
        const email = registerForm.querySelector('[name="email"]')
            ?.value.trim();
        const password = registerForm.querySelector('[name="password"]')
            ?.value;
        const confirmation = registerForm.querySelector(
            '[name="password_confirmation"]'
        )?.value;

        if (!username || !email || !password || !confirmation) {
            showStatus(status, "Please complete all registration fields.");
            return;
        }

        if (password !== confirmation) {
            showStatus(status, "Your passwords do not match.");
            return;
        }

        if (password.length < 8) {
            showStatus(
                status,
                "Your password must be at least 8 characters."
            );
            return;
        }

        const verifyUrl = new URL(
            registerForm.dataset.verifyUrl,
            window.location.origin
        ).href;

        if (submitButton) submitButton.disabled = true;

        try {
            showStatus(status, "Creating your account...");

            await setPersistence(auth, browserLocalPersistence);

            const result = await createUserWithEmailAndPassword(
                auth,
                email,
                password
            );

            sessionStorage.setItem(
                "sjpassdown_pending_username",
                username
            );

            await sendEmailVerification(result.user, {
                url: verifyUrl,
                handleCodeInApp: false,
            });

            showStatus(
                status,
                "Verification email sent! Open it, click the verification " +
                "link, and return to the verification page."
            );

            window.location.assign(verifyUrl);
        } catch (error) {
            const messages = {
                "auth/email-already-in-use":
                    "This email already has a Firebase account. Try logging in.",
                "auth/invalid-email":
                    "Please enter a valid email address.",
                "auth/weak-password":
                    "Please choose a stronger password.",
                "auth/operation-not-allowed":
                    "Email/password sign-in is not enabled in Firebase.",
                "auth/too-many-requests":
                    "Too many attempts. Please wait before trying again.",
            };

            showStatus(
                status,
                messages[error.code] ||
                error.message ||
                "Registration failed. Please try again."
            );
        } finally {
            if (submitButton) submitButton.disabled = false;
        }
    });
}

// --------------------------------------------------
// LOGIN
// --------------------------------------------------

const loginForm = document.querySelector("[data-firebase-login]");

if (loginForm) {
    loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const status = loginForm.querySelector("[data-firebase-status]");
        const submitButton = loginForm.querySelector(
            'button[type="submit"]'
        );

        const email = loginForm.querySelector('[name="email"]')
            ?.value.trim();
        const password = loginForm.querySelector('[name="password"]')
            ?.value;

        if (!email || !password) {
            showStatus(status, "Please enter your email and password.");
            return;
        }

        if (submitButton) submitButton.disabled = true;

        try {
            showStatus(status, "Logging in...");

            await setPersistence(auth, browserLocalPersistence);

            const result = await signInWithEmailAndPassword(
                auth,
                email,
                password
            );

            await result.user.reload();

            if (!result.user.emailVerified) {
                showStatus(
                    status,
                    "Your email is not verified yet. Open the verification " +
                    "email and click its link before logging in."
                );
                return;
            }

            const idToken = await result.user.getIdToken(true);
            const csrfToken = getCsrfToken(loginForm);
            const endpoint = loginForm.dataset.loginUrl;
            const nextInput = loginForm.querySelector('[name="next"]');
            const next = nextInput?.value || "/";

            const response = await fetch(endpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({
                    idToken,
                    next,
                }),
            });

            const data = await readResponse(response);

            if (!response.ok) {
                throw new Error(
                    data.error || "Login failed. Please try again."
                );
            }

            showStatus(status, "Login successful! Redirecting...");
            window.location.assign(data.redirect || "/");
        } catch (error) {
            const messages = {
                "auth/invalid-credential":
                    "Incorrect email or password. Please check your details.",
                "auth/user-not-found":
                    "No Firebase account was found for that email. Please sign up.",
                "auth/wrong-password":
                    "Incorrect email or password. Please try again.",
                "auth/invalid-email":
                    "Please enter a valid email address.",
                "auth/too-many-requests":
                    "Too many login attempts. Please wait and try again.",
                "auth/network-request-failed":
                    "Network error. Check your internet connection and try again.",
            };

            showStatus(
                status,
                messages[error.code] ||
                error.message ||
                "Login failed. Please try again."
            );
        } finally {
            if (submitButton) submitButton.disabled = false;
        }
    });
}

// --------------------------------------------------
// EMAIL VERIFICATION AND REGISTRATION RECOVERY
// --------------------------------------------------

const verificationPage = document.querySelector(
    "[data-firebase-verification-page]"
);

if (verificationPage) {
    const status = verificationPage.querySelector("[data-firebase-status]");
    const endpoint = verificationPage.dataset.completeUrl;
    const csrfToken = getCsrfToken(verificationPage);

    const usernameInput = verificationPage.querySelector(
        '[name="resume_username"]'
    );
    const emailInput = verificationPage.querySelector(
        '[name="resume_email"]'
    );
    const passwordInput = verificationPage.querySelector(
        '[name="resume_password"]'
    );
    const resumeButton = verificationPage.querySelector(
        "[data-resume-registration]"
    );
    const resendButton = verificationPage.querySelector(
        "[data-resend-verification]"
    );

    // Restore the username if it is still in this browser session.
    if (usernameInput) {
        usernameInput.value =
            sessionStorage.getItem("sjpassdown_pending_username") || "";
    }

    async function finishRegistration(user, username) {
        if (!username) {
            showStatus(status, "Please enter the username you registered with.");
            return;
        }

        showStatus(status, "Checking your email verification...");

        await user.reload();

        if (!user.emailVerified) {
            showStatus(
                status,
                "Your email is not verified yet. Open the Firebase verification " +
                "email, click its link, and try again."
            );
            return;
        }

        showStatus(status, "Email verified! Finishing your registration...");

        await completeDjangoRegistration({
            user,
            username,
            endpoint,
            csrfToken,
            status,
        });
    }

    // Attempt automatic completion if Firebase still has a signed-in user.
    async function checkExistingSession() {
        const user = auth.currentUser;

        if (!user) {
            showStatus(
                status,
                "Your email verification page is ready. Enter your original " +
                "username, email address and password below to finish registration."
            );
            return;
        }

        try {
            const username =
                usernameInput?.value.trim() ||
                sessionStorage.getItem("sjpassdown_pending_username") ||
                "";

            await finishRegistration(user, username);
        } catch (error) {
            showStatus(
                status,
                error.message || "Could not finish registration. Please try again."
            );
        }
    }

    if (resumeButton) {
        resumeButton.addEventListener("click", async () => {
            const username = usernameInput?.value.trim();
            const email = emailInput?.value.trim();
            const password = passwordInput?.value;

            if (!username || !email || !password) {
                showStatus(
                    status,
                    "Please enter your username, email address and password."
                );
                return;
            }

            resumeButton.disabled = true;

            try {
                showStatus(status, "Signing in to your existing Firebase account...");

                await setPersistence(auth, browserLocalPersistence);

                const result = await signInWithEmailAndPassword(
                    auth,
                    email,
                    password
                );

                await result.user.reload();

                if (!result.user.emailVerified) {
                    showStatus(
                        status,
                        "Your email is not verified yet. Open the verification " +
                        "email first, then try again."
                    );
                    return;
                }

                sessionStorage.setItem(
                    "sjpassdown_pending_username",
                    username
                );

                await finishRegistration(result.user, username);
            } catch (error) {
                const messages = {
                    "auth/invalid-credential":
                        "The email or password is incorrect. Please check them and try again.",
                    "auth/user-not-found":
                        "No Firebase account was found for that email.",
                    "auth/wrong-password":
                        "The email or password is incorrect. Please try again.",
                    "auth/invalid-email":
                        "Please enter a valid email address.",
                    "auth/too-many-requests":
                        "Too many attempts. Please wait before trying again.",
                    "auth/network-request-failed":
                        "Network error. Check your internet connection and try again.",
                };

                showStatus(
                    status,
                    messages[error.code] ||
                    error.message ||
                    "Could not finish registration. Please try again."
                );
            } finally {
                resumeButton.disabled = false;
            }
        });
    }

    // Resend a verification email when a Firebase user is signed in.
    if (resendButton) {
        resendButton.addEventListener("click", async () => {
            resendButton.disabled = true;

            try {
                let user = auth.currentUser;

                if (!user) {
                    showStatus(
                        status,
                        "First enter your email and password and click Finish Registration. " +
                        "Once signed in, you can request another verification email."
                    );
                    return;
                }

                await user.reload();

                if (user.emailVerified) {
                    showStatus(status, "Your email is already verified.");
                    return;
                }

                await sendEmailVerification(user, {
                    url: window.location.href,
                    handleCodeInApp: false,
                });

                showStatus(status, "A new verification email has been sent.");
            } catch (error) {
                showStatus(
                    status,
                    error.message || "Could not resend the verification email."
                );
            } finally {
                resendButton.disabled = false;
            }
        });
    }

    checkExistingSession();
}

export { app, auth };
