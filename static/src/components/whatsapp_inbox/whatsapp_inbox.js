/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

export class WhatsappInbox extends Component {
    static template = "otm_whatsapp_coexistence.WhatsappInbox";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            phones: [],
            selectedPhoneId: "all",
            conversations: [],
            selectedConversationId: null,
            messages: [],
            draft: "",
            loading: false,
        });
        onWillStart(async () => {
            await this.loadPhones();
            await this.loadConversations();
        });
    }

    async loadPhones() {
        // Read-only listing - ORM call, normal ir.rule/ACL enforced.
        this.state.phones = await this.orm.searchRead(
            "otm.whatsapp.phone",
            [],
            ["id", "name", "display_phone_number", "unread_count"]
        );
    }

    async loadConversations() {
        this.state.loading = true;
        const domain =
            this.state.selectedPhoneId === "all"
                ? []
                : [["phone_id", "=", this.state.selectedPhoneId]];
        this.state.conversations = await this.orm.searchRead(
            "otm.whatsapp.conversation",
            domain,
            ["id", "name", "phone_id", "last_message", "last_message_date", "unread_count", "status"],
            { order: "last_message_date desc", limit: 80 }
        );
        this.state.loading = false;
    }

    async selectPhone(phoneId) {
        this.state.selectedPhoneId = phoneId;
        await this.loadConversations();
    }

    async openConversation(conversationId) {
        this.state.selectedConversationId = conversationId;
        this.state.messages = await this.orm.searchRead(
            "otm.whatsapp.message",
            [["conversation_id", "=", conversationId]],
            ["id", "direction", "body", "message_type", "state", "create_date"],
            { order: "create_date asc", limit: 200 }
        );
        await this.orm.call("otm.whatsapp.conversation", "mark_read", [[conversationId]]);
        await this.loadConversations();
    }

    get selectedConversation() {
        return this.state.conversations.find((c) => c.id === this.state.selectedConversationId);
    }

    onDraftKeydown(ev) {
        if (ev.key === "Enter") {
            this.sendMessage();
        }
    }

    async sendMessage() {
        const body = this.state.draft.trim();
        const conv = this.selectedConversation;
        if (!body || !conv) {
            return;
        }
        this.state.draft = "";
        const messageId = await this.orm.create("otm.whatsapp.message", [
            {
                phone_id: conv.phone_id[0],
                conversation_id: conv.id,
                direction: "out",
                message_type: "text",
                body: body,
                state: "queued",
            },
        ]);
        await this.orm.call("otm.whatsapp.message", "action_send_now", [[messageId]]);
        await this.openConversation(conv.id);
    }
}

registry.category("actions").add("otm_whatsapp_inbox", WhatsappInbox);
