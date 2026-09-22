const kQueryArg = "q";
const kResultsArg = "show-results";

// If items don't provide a URL, then both the navigator and the onSelect
// function aren't called (and therefore, the default implementation is used)
//
// We're using this sentinel URL to signal to those handlers that this
// item is a more item (along with the type) and can be handled appropriately
const kItemTypeMoreHref = "0767FDFD-0422-4E5A-BC8A-3BE11E5BBA05";

// Capture search params and clean ?q= from URL at module load time, before
// any DOMContentLoaded handlers run. quarto-nav.js resolves all <a> hrefs
// against window.location during DOMContentLoaded — if ?q= is still present,
// every link on the page gets the query param baked into its href.
const currentUrl = new URL(window.location);
const kQuery = currentUrl.searchParams.get(kQueryArg);
if (kQuery) {
  const replacementUrl = new URL(window.location);
  replacementUrl.searchParams.delete(kQueryArg);
  window.history.replaceState({}, "", replacementUrl);
}

window.document.addEventListener("DOMContentLoaded", function (_event) {
  // Ensure that search is available on this page. If it isn't,
  // should return early and not do anything
  var searchEl = window.document.getElementById("quarto-search");
  if (!searchEl) return;

  const { autocomplete } = window["@algolia/autocomplete-js"];

  let quartoSearchOptions = {};
  let language = {};
  const searchOptionEl = window.document.getElementById(
    "quarto-search-options"
  );
  if (searchOptionEl) {
    const jsonStr = searchOptionEl.textContent;
    quartoSearchOptions = JSON.parse(jsonStr);
    language = quartoSearchOptions.language;
  }

  // note the search mode
  if (quartoSearchOptions.type === "overlay") {
    searchEl.classList.add("type-overlay");
  } else {
    searchEl.classList.add("type-textbox");
  }

  // Used to determine highlighting behavior for this page
  // A `q` query param is expected when the user follows a search
  // to this page
  const query = kQuery;
  const showSearchResults = currentUrl.searchParams.get(kResultsArg);
  const mainEl = window.document.querySelector("main");

  // highlight matches on the page
  if (query && mainEl) {
    highlight(query, mainEl);

    // Activate tabs on pageshow — after tabsets.js restores localStorage state.
    // tabsets.js registers its pageshow handler during module execution (before
    // DOMContentLoaded). By registering ours during DOMContentLoaded, listener
    // ordering guarantees we run after tabsets.js — so search activation wins.
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) {
        for (const mark of mainEl.querySelectorAll("mark")) {
          openAllTabsetsContainingEl(mark);
        }
        // Only scroll to first match when there's no hash fragment.
        // With a hash, the browser already scrolled to the target section.
        if (!currentUrl.hash) {
          requestAnimationFrame(() => scrollToFirstVisibleMatch(mainEl));
        }
      }
    }, { once: true });
  }

  // function to clear highlighting on the page when the search query changes
  // (e.g. if the user edits the query or clears it)
  let highlighting = true;
  const resetHighlighting = (searchTerm) => {
    if (mainEl && highlighting && query && searchTerm !== query) {
      clearHighlight(query, mainEl);
      highlighting = false;
    }
  };

  // Responsively switch to overlay mode if the search is present on the navbar
  // Note that switching the sidebar to overlay mode requires more coordinate (not just
  // the media query since we generate different HTML for sidebar overlays than we do
  // for sidebar input UI)
  const detachedMediaQuery =
    quartoSearchOptions.type === "overlay" ? "all" : "(max-width: 991px)";

  // If configured, include the analytics client to send insights
  const plugins = configurePlugins(quartoSearchOptions);

  let lastState = null;
  const { setIsOpen, setQuery, setCollections } = autocomplete({
    container: searchEl,
    detachedMediaQuery: detachedMediaQuery,
    defaultActiveItemId: 0,
    panelContainer: "#quarto-search-results",
    panelPlacement: quartoSearchOptions["panel-placement"],
    debug: false,
    openOnFocus: true,
    plugins,
    classNames: {
      form: "d-flex",
    },
    placeholder: language["search-text-placeholder"],
    translations: {
      clearButtonTitle: language["search-clear-button-title"],
      detachedCancelButtonText: language["search-detached-cancel-button-title"],
      submitButtonTitle: language["search-submit-button-title"],
    },
    initialState: {
      query,
    },
    getItemUrl({ item }) {
      return item.href;
    },
    onStateChange({ state }) {
      // If this is a file URL, note that

      // Perhaps reset highlighting
      resetHighlighting(state.query);

      // If the panel just opened, ensure the panel is positioned properly
      if (state.isOpen) {
        if (lastState && !lastState.isOpen) {
          setTimeout(() => {
            positionPanel(quartoSearchOptions["panel-placement"]);
          }, 150);
        }
      }

      // Perhaps show the copy link
      showCopyLink(state.query, quartoSearchOptions);

      lastState = state;
    },
    reshape({ sources, state }) {
      return sources.map((source) => {
        try {
          const items = source.getItems();

          // Validate the items
          validateItems(items);

          // group the items by document
          const groupedItems = new Map();
          items.forEach((item) => {
            const hrefParts = item.href.split("#");
            const baseHref = hrefParts[0];
            const isDocumentItem = hrefParts.length === 1;

            const items = groupedItems.get(baseHref);
            if (!items) {
              groupedItems.set(baseHref, [item]);
            } else {
              // If the href for this item matches the document
              // exactly, place this item first as it is the item that represents
              // the document itself
              if (isDocumentItem) {
                items.unshift(item);
              } else {
                items.push(item);
              }
              groupedItems.set(baseHref, items);
            }
          });

          const reshapedItems = [];
          let count = 1;
          for (const [_key, value] of groupedItems) {
            const firstItem = value[0];
            reshapedItems.push({
              ...firstItem,
              type: kItemTypeDoc,
            });

            const collapseMatches = quartoSearchOptions["collapse-after"];
            const collapseCount =
              typeof collapseMatches === "number" ? collapseMatches : 1;

            if (value.length > 1) {
              const target = `search-more-${count}`;
              const isExpanded =
                state.context.expanded &&
                state.context.expanded.includes(target);

              const remainingCount = value.length - collapseCount;

              for (let i = 1; i < value.length; i++) {
                if (collapseMatches && i === collapseCount) {
                  reshapedItems.push({
                    target,
                    title: isExpanded
                      ? language["search-hide-matches-text"]
                      : remainingCount === 1
                        ? `${remainingCount} ${language["search-more-match-text"]}`
                        : `${remainingCount} ${language["search-more-matches-text"]}`,
                    type: kItemTypeMore,
                    href: kItemTypeMoreHref,
                  });
                }

                if (isExpanded || !collapseMatches || i < collapseCount) {
                  reshapedItems.push({
                    ...value[i],
                    type: kItemTypeItem,
                    target,
                  });
                }
              }
            }
            count += 1;
          }

          return {
            ...source,
            getItems() {
              return reshapedItems;
            },
          };
        } catch (error) {
          // Some form of error occurred
          return {
            ...source,
            getItems() {
              return [
                {
                  title: error.name || "An Error Occurred While Searching",
                  text:
                    error.message ||
                    "An unknown error occurred while attempting to perform the requested search.",
                  type: kItemTypeError,
                },
              ];
            },
          };
        }
      });
    },
    navigator: {
      navigate({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          window.location.assign(itemUrl);
        }
      },
      navigateNewTab({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          const windowReference = window.open(itemUrl, "_blank", "noopener");
          if (windowReference) {
            windowReference.focus();
          }
        }
      },
      navigateNewWindow({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          window.open(itemUrl, "_blank", "noopener");
        }
      },
    },
    getSources({ state, setContext, setActiveItemId, refresh }) {
      return [
        {
          sourceId: "documents",
          getItemUrl({ item }) {
            if (item.href) {
              return offsetURL(item.href);
            } else {
              return undefined;
            }
          },
          onSelect({
            item,
            state,
            setContext,
            setIsOpen,
            setActiveItemId,
            refresh,
          }) {
            if (item.type === kItemTypeMore) {
              toggleExpanded(item, state, setContext, setActiveItemId, refresh);

              // Toggle more
              setIsOpen(true);
            }
          },
          getItems({ query }) {
            if (query === null || query === "") {
              return [];
            }

            const limit = quartoSearchOptions.limit;
            if (quartoSearchOptions.algolia) {
              return algoliaSearch(query, limit, quartoSearchOptions.algolia);
            } else {
              // Fuse search options
              const fuseSearchOptions = {
                isCaseSensitive: false,
                shouldSort: true,
                minMatchCharLength: 2,
                limit: limit,
              };

              return readSearchData().then(function (fuse) {
                return fuseSearch(query, fuse, fuseSearchOptions);
              });
            }
          },
          templates: {
            noResults({ createElement }) {
              const hasQuery = lastState.query;

              return createElement(
                "div",
                {
                  class: `quarto-search-no-results${hasQuery ? "" : " no-query"
                    }`,
                },
                language["search-no-results-text"]
              );
            },
            header({ items, createElement }) {
              // count the documents
              const count = items.filter((item) => {
                return item.type === kItemTypeDoc;
              }).length;

              if (count > 0) {
                return createElement(
                  "div",
                  { class: "search-result-header" },
                  `${count} ${language["search-matching-documents-text"]}`
                );
              } else {
                return createElement(
                  "div",
                  { class: "search-result-header-no-results" },
                  ``
                );
              }
            },
            footer({ _items, createElement }) {
              if (
                quartoSearchOptions.algolia &&
                quartoSearchOptions.algolia["show-logo"]
              ) {
                const libDir = quartoSearchOptions.algolia["libDir"];
                const logo = createElement("img", {
                  src: offsetURL(
                    `${libDir}/quarto-search/search-by-algolia.svg`
                  ),
                  class: "algolia-search-logo",
                });
                return createElement(
                  "a",
                  { href: "http://www.algolia.com/" },
                  logo
                );
              }
            },

            item({ item, createElement }) {
              if (item.text && item.href && !item.href.includes('?q=')) {
                const [main, hash] = item.href.split('#')
                const hashAppend = hash ? '#' + hash : ''
                item.href = main + '?q=' + encodeURIComponent(state.query) + hashAppend
              }

              return renderItem(
                item,
                createElement,
                state,
                setActiveItemId,
                setContext,
                refresh,
                quartoSearchOptions
              );
            },
          },
        },
      ];
    },
  });

  window.quartoOpenSearch = () => {
    setIsOpen(false);
    setIsOpen(true);
    focusSearchInput();
  };

  document.addEventListener("keyup", (event) => {
    const { key } = event;
    const kbds = quartoSearchOptions["keyboard-shortcut"];
    const focusedEl = document.activeElement;

    const isFormElFocused = [
      "input",
      "select",
      "textarea",
      "button",
      "option",
    ].find((tag) => {
      return focusedEl.tagName.toLowerCase() === tag;
    });

    if (
      kbds &&
      kbds.includes(key) &&
      !isFormElFocused &&
      !document.activeElement.isContentEditable
    ) {
      event.preventDefault();
      window.quartoOpenSearch();
    }
  });

  // Remove the labeleledby attribute since it is pointing
  // to a non-existent label
  if (quartoSearchOptions.type === "overlay") {
    const inputEl = window.document.querySelector(
      "#quarto-search .aa-Autocomplete"
    );
    if (inputEl) {
      inputEl.removeAttribute("aria-labelledby");
    }
  }

  function throttle(func, wait) {
    let waiting = false;
    return function () {
      if (!waiting) {
        func.apply(this, arguments);
        waiting = true;
        setTimeout(function () {
          waiting = false;
        }, wait);
      }
    };
  }

  // If the main document scrolls dismiss the search results
  // (otherwise, since they're floating in the document they can scroll with the document)
  window.document.body.onscroll = throttle(() => {
    // Only do this if we're not detached
    // Bug #7117
    // This will happen when the keyboard is shown on ios (resulting in a scroll)
    // which then closed the search UI
    if (!window.matchMedia(detachedMediaQuery).matches) {
      setIsOpen(false);
    }
  }, 50);

  if (showSearchResults) {
    setIsOpen(true);
    focusSearchInput();
  }
});

function configurePlugins(quartoSearchOptions) {
  const autocompletePlugins = [];
  const algoliaOptions = quartoSearchOptions.algolia;
  if (
    algoliaOptions &&
    algoliaOptions["analytics-events"] &&
    algoliaOptions["search-only-api-key"] &&
    algoliaOptions["application-id"]
  ) {
    const apiKey = algoliaOptions["search-only-api-key"];
    const appId = algoliaOptions["application-id"];

    // Aloglia insights may not be loaded because they require cookie consent
    // Use deferred loading so events will start being recorded when/if consent
    // is granted.
    const algoliaInsightsDeferredPlugin = deferredLoadPlugin(() => {
      if (
        window.aa &&
        window["@algolia/autocomplete-plugin-algolia-insights"]
      ) {
        // Check if cookie consent is enabled from search options
        const cookieConsentEnabled = algoliaOptions["cookie-consent-enabled"] || false;

        // Generate random session token only when cookies are disabled
        const userToken = cookieConsentEnabled ? undefined : Array.from(Array(20), () =>
          Math.floor(Math.random() * 36).toString(36)
        ).join("");

        window.aa("init", {
          appId,
          apiKey,
          useCookie: cookieConsentEnabled,
          userToken: userToken,
        });

        const { createAlgoliaInsightsPlugin } =
          window["@algolia/autocomplete-plugin-algolia-insights"];
        // Register the insights client
        const algoliaInsightsPlugin = createAlgoliaInsightsPlugin({
          insightsClient: window.aa,
          onItemsChange({ insights, insightsEvents }) {
            const events = insightsEvents.flatMap((event) => {
              // This API limits the number of items per event to 20
              const chunkSize = 20;
              const itemChunks = [];
              const eventItems = event.items;
              for (let i = 0; i < eventItems.length; i += chunkSize) {
                itemChunks.push(eventItems.slice(i, i + chunkSize));
              }
              // Split the items into multiple events that can be sent
              const events = itemChunks.map((items) => {
                return {
                  ...event,
                  items,
                };
              });
              return events;
            });

            for (const event of events) {
              insights.viewedObjectIDs(event);
            }
          },
        });
        return algoliaInsightsPlugin;
      }
    });

    // Add the plugin
    autocompletePlugins.push(algoliaInsightsDeferredPlugin);
    return autocompletePlugins;
  }
}

// For plugins that may not load immediately, create a wrapper
// plugin and forward events and plugin data once the plugin
// is initialized. This is useful for cases like cookie consent
// which may prevent the analytics insights event plugin from initializing
// immediately.
function deferredLoadPlugin(createPlugin) {
  let plugin = undefined;
  let subscribeObj = undefined;
  const wrappedPlugin = () => {
    if (!plugin && subscribeObj) {
      plugin = createPlugin();
      if (plugin && plugin.subscribe) {
        plugin.subscribe(subscribeObj);
      }
    }
    return plugin;
  };

  return {
    subscribe: (obj) => {
      subscribeObj = obj;
    },
    onStateChange: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onStateChange) {
        plugin.onStateChange(obj);
      }
    },
    onSubmit: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onSubmit) {
        plugin.onSubmit(obj);
      }
    },
    onReset: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onReset) {
        plugin.onReset(obj);
      }
    },
    getSources: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.getSources) {
        return plugin.getSources(obj);
      } else {
        return Promise.resolve([]);
      }
    },
    data: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.data) {
        plugin.data(obj);
      }
    },
  };
}

function validateItems(items) {
  // Validate the first item
  if (items.length > 0) {
    const item = items[0];
    const missingFields = [];
    if (item.href == undefined) {
      missingFields.push("href");
    }
    if (!item.title == undefined) {
      missingFields.push("title");
    }
    if (!item.text == undefined) {
      missingFields.push("text");
    }

    if (missingFields.length === 1) {
      throw {
        name: `Error: Search index is missing the <code>${missingFields[0]}</code> field.`,
        message: `The items being returned for this search do not include all the required fields. Please ensure that your index items include the <code>${missingFields[0]}</code> field or use <code>index-fields</code> in your <code>_quarto.yml</code> file to specify the field names.`,
      };
    } else if (missingFields.length > 1) {
      const missingFieldList = missingFields
        .map((field) => {
          return `<code>${field}</code>`;
        })
        .join(", ");

      throw {
        name: `Error: Search index is missing the following fields: ${missingFieldList}.`,
        message: `The items being returned for this search do not include all the required fields. Please ensure that your index items includes the following fields: ${missingFieldList}, or use <code>index-fields</code> in your <code>_quarto.yml</code> file to specify the field names.`,
      };
    }
  }
}

let lastQuery = null;
function showCopyLink(query, options) {
  const language = options.language;
  lastQuery = query;
  // Insert share icon
  const inputSuffixEl = window.document.body.querySelector(
    ".aa-Form .aa-InputWrapperSuffix"
  );

  if (inputSuffixEl) {
    let copyButtonEl = window.document.body.querySelector(
      ".aa-Form .aa-InputWrapperSuffix .aa-CopyButton"
    );

    if (copyButtonEl === null) {
      copyButtonEl = window.document.createElement("button");
      copyButtonEl.setAttribute("class", "aa-CopyButton");
      copyButtonEl.setAttribute("type", "button");
      copyButtonEl.setAttribute("title", language["search-copy-link-title"]);
      copyButtonEl.onmousedown = (e) => {
        e.preventDefault();
        e.stopPropagation();
      };

      const linkIcon = "bi-clipboard";
      const checkIcon = "bi-check2";

      const shareIconEl = window.document.createElement("i");
      shareIconEl.setAttribute("class", `bi ${linkIcon}`);
      copyButtonEl.appendChild(shareIconEl);
      inputSuffixEl.prepend(copyButtonEl);

      const clipboard = new window.ClipboardJS(".aa-CopyButton", {
        text: function (_trigger) {
          const copyUrl = new URL(window.location);
          copyUrl.searchParams.set(kQueryArg, lastQuery);
          copyUrl.searchParams.set(kResultsArg, "1");
          return copyUrl.toString();
        },
      });
      clipboard.on("success", function (e) {
        // Focus the input

        // button target
        const button = e.trigger;
        const icon = button.querySelector("i.bi");

        // flash "checked"
        icon.classList.add(checkIcon);
        icon.classList.remove(linkIcon);
        setTimeout(function () {
          icon.classList.remove(checkIcon);
          icon.classList.add(linkIcon);
        }, 1000);
      });
    }

    // If there is a query, show the link icon
    if (copyButtonEl) {
      if (lastQuery && options["copy-button"]) {
        copyButtonEl.style.display = "flex";
      } else {
        copyButtonEl.style.display = "none";
      }
    }
  }
}

/* Search Index Handling */
// create the index
var fuseIndex = undefined;
var shownWarning = false;

// fuse index options
const kFuseIndexOptions = {
  keys: [
    { name: "title", weight: 20 },
    { name: "section", weight: 20 },
    { name: "text", weight: 10 },
  ],
  ignoreLocation: true,
  threshold: 0.1,
};

async function readSearchData() {
  // Initialize the search index on demand
  if (fuseIndex === undefined) {
    if (false /* moondata: 索引已内嵌，file:// 下同样可用 */) {
      window.alert(
        "Search requires JavaScript features disabled when running in file://... URLs. In order to use search, please run this document in a web server."
      );
      shownWarning = true;
      return;
    }
    const fuse = new window.Fuse([], kFuseIndexOptions);

    // fetch the main search.json
    const response = __moondataOfflineSearchResponse();
    if (response.status == 200) {
      return response.json().then(function (searchDocs) {
        searchDocs.forEach(function (searchDoc) {
          fuse.add(searchDoc);
        });
        fuseIndex = fuse;
        return fuseIndex;
      });
    } else {
      return Promise.reject(
        new Error(
          "Unexpected status from search index request: " + response.status
        )
      );
    }
  }

  return fuseIndex;
}

function inputElement() {
  return window.document.body.querySelector(".aa-Form .aa-Input");
}

function focusSearchInput() {
  setTimeout(() => {
    const inputEl = inputElement();
    if (inputEl) {
      inputEl.focus();
    }
  }, 50);
}

/* Panels */
const kItemTypeDoc = "document";
const kItemTypeMore = "document-more";
const kItemTypeItem = "document-item";
const kItemTypeError = "error";

function renderItem(
  item,
  createElement,
  state,
  setActiveItemId,
  setContext,
  refresh,
  quartoSearchOptions
) {
  switch (item.type) {
    case kItemTypeDoc:
      return createDocumentCard(
        createElement,
        "file-richtext",
        item.title,
        item.section,
        item.text,
        item.href,
        item.crumbs,
        quartoSearchOptions
      );
    case kItemTypeMore:
      return createMoreCard(
        createElement,
        item,
        state,
        setActiveItemId,
        setContext,
        refresh
      );
    case kItemTypeItem:
      return createSectionCard(
        createElement,
        item.section,
        item.text,
        item.href
      );
    case kItemTypeError:
      return createErrorCard(createElement, item.title, item.text);
    default:
      return undefined;
  }
}

function createDocumentCard(
  createElement,
  icon,
  title,
  section,
  text,
  href,
  crumbs,
  quartoSearchOptions
) {
  const iconEl = createElement("i", {
    class: `bi bi-${icon} search-result-icon`,
  });
  const titleEl = createElement("p", { class: "search-result-title" }, title);
  const titleContents = [iconEl, titleEl];
  const showParent = quartoSearchOptions["show-item-context"];
  if (crumbs && showParent) {
    let crumbsOut = undefined;
    const crumbClz = ["search-result-crumbs"];
    if (showParent === "root") {
      crumbsOut = crumbs.length > 1 ? crumbs[0] : undefined;
    } else if (showParent === "parent") {
      crumbsOut = crumbs.length > 1 ? crumbs[crumbs.length - 2] : undefined;
    } else {
      crumbsOut = crumbs.length > 1 ? crumbs.join(" > ") : undefined;
      crumbClz.push("search-result-crumbs-wrap");
    }

    const crumbEl = createElement(
      "p",
      { class: crumbClz.join(" ") },
      crumbsOut
    );
    titleContents.push(crumbEl);
  }

  const titleContainerEl = createElement(
    "div",
    { class: "search-result-title-container" },
    titleContents
  );

  const textEls = [];
  if (section) {
    const sectionEl = createElement(
      "p",
      { class: "search-result-section" },
      section
    );
    textEls.push(sectionEl);
  }
  const descEl = createElement("p", {
    class: "search-result-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });
  textEls.push(descEl);

  const textContainerEl = createElement(
    "div",
    { class: "search-result-text-container" },
    textEls
  );

  const containerEl = createElement(
    "div",
    {
      class: "search-result-container",
    },
    [titleContainerEl, textContainerEl]
  );

  const linkEl = createElement(
    "a",
    {
      href: offsetURL(href),
      class: "search-result-link",
    },
    containerEl
  );

  const classes = ["search-result-doc", "search-item"];
  if (!section) {
    classes.push("document-selectable");
  }

  return createElement(
    "div",
    {
      class: classes.join(" "),
    },
    linkEl
  );
}

function createMoreCard(
  createElement,
  item,
  state,
  setActiveItemId,
  setContext,
  refresh
) {
  const moreCardEl = createElement(
    "div",
    {
      class: "search-result-more search-item",
      onClick: (e) => {
        // Handle expanding the sections by adding the expanded
        // section to the list of expanded sections
        toggleExpanded(item, state, setContext, setActiveItemId, refresh);
        e.stopPropagation();
      },
    },
    item.title
  );

  return moreCardEl;
}

function toggleExpanded(item, state, setContext, setActiveItemId, refresh) {
  const expanded = state.context.expanded || [];
  if (expanded.includes(item.target)) {
    setContext({
      expanded: expanded.filter((target) => target !== item.target),
    });
  } else {
    setContext({ expanded: [...expanded, item.target] });
  }

  refresh();
  setActiveItemId(item.__autocomplete_id);
}

function createSectionCard(createElement, section, text, href) {
  const sectionEl = createSection(createElement, section, text, href);
  return createElement(
    "div",
    {
      class: "search-result-doc-section search-item",
    },
    sectionEl
  );
}

function createSection(createElement, title, text, href) {
  const descEl = createElement("p", {
    class: "search-result-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });

  const titleEl = createElement("p", { class: "search-result-section" }, title);
  const linkEl = createElement(
    "a",
    {
      href: offsetURL(href),
      class: "search-result-link",
    },
    [titleEl, descEl]
  );
  return linkEl;
}

function createErrorCard(createElement, title, text) {
  const descEl = createElement("p", {
    class: "search-error-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });

  const titleEl = createElement("p", {
    class: "search-error-title",
    dangerouslySetInnerHTML: {
      __html: `<i class="bi bi-exclamation-circle search-error-icon"></i> ${title}`,
    },
  });
  const errorEl = createElement("div", { class: "search-error" }, [
    titleEl,
    descEl,
  ]);
  return errorEl;
}

function positionPanel(pos) {
  const panelEl = window.document.querySelector(
    "#quarto-search-results .aa-Panel"
  );
  const inputEl = window.document.querySelector(
    "#quarto-search .aa-Autocomplete"
  );

  if (panelEl && inputEl) {
    panelEl.style.top = `${Math.round(panelEl.offsetTop)}px`;
    if (pos === "start") {
      panelEl.style.left = `${Math.round(inputEl.left)}px`;
    } else {
      panelEl.style.right = `${Math.round(inputEl.offsetRight)}px`;
    }
  }
}

/* Highlighting */
// highlighting functions
function highlightMatch(query, text) {
  if (text) {
    const start = text.toLowerCase().indexOf(query.toLowerCase());
    if (start !== -1) {
      const startMark = "<mark class='search-match'>";
      const endMark = "</mark>";

      const end = start + query.length;
      text =
        text.slice(0, start) +
        startMark +
        text.slice(start, end) +
        endMark +
        text.slice(end);
      const startInfo = clipStart(text, start);
      const endInfo = clipEnd(
        text,
        startInfo.position + startMark.length + endMark.length
      );
      text =
        startInfo.prefix +
        text.slice(startInfo.position, endInfo.position) +
        endInfo.suffix;

      return text;
    } else {
      return text;
    }
  } else {
    return text;
  }
}

function clipStart(text, pos) {
  const clipStart = pos - 50;
  if (clipStart < 0) {
    // This will just return the start of the string
    return {
      position: 0,
      prefix: "",
    };
  } else {
    // We're clipping before the start of the string, walk backwards to the first space.
    const spacePos = findSpace(text, pos, -1);
    return {
      position: spacePos.position,
      prefix: "",
    };
  }
}

function clipEnd(text, pos) {
  const clipEnd = pos + 200;
  if (clipEnd > text.length) {
    return {
      position: text.length,
      suffix: "",
    };
  } else {
    const spacePos = findSpace(text, clipEnd, 1);
    return {
      position: spacePos.position,
      suffix: spacePos.clipped ? "…" : "",
    };
  }
}

function findSpace(text, start, step) {
  let stepPos = start;
  while (stepPos > -1 && stepPos < text.length) {
    const char = text[stepPos];
    if (char === " " || char === "," || char === ":") {
      return {
        position: step === 1 ? stepPos : stepPos - step,
        clipped: stepPos > 1 && stepPos < text.length,
      };
    }
    stepPos = stepPos + step;
  }

  return {
    position: stepPos - step,
    clipped: false,
  };
}

// removes highlighting as implemented by the mark tag
function clearHighlight(searchterm, el) {
  const childNodes = el.childNodes;
  for (let i = childNodes.length - 1; i >= 0; i--) {
    const node = childNodes[i];
    if (node.nodeType === Node.ELEMENT_NODE) {
      if (
        node.tagName === "MARK" &&
        node.innerText.toLowerCase() === searchterm.toLowerCase()
      ) {
        el.replaceChild(document.createTextNode(node.innerText), node);
      } else {
        clearHighlight(searchterm, node);
      }
    }
  }
}

/** Get all html nodes under the given `root` that don't have children. */
function getLeafNodes(root) {
  let leaves = [];

  function traverse(node) {
    if (node.childNodes.length === 0) {
      leaves.push(node);
    } else {
      node.childNodes.forEach(traverse);
    }
  }

  traverse(root);
  return leaves;
}
/** create and return `<mark>${txt}</mark>` */
const markEl = txt => {
  const el = document.createElement("mark");
  el.appendChild(document.createTextNode(txt));
  return el
}
/** get all ancestors of an element matching the given css selector */
const matchAncestors = (el, selector) => {
  let ancestors = [];
  while (el) {
    if (el.matches?.(selector)) ancestors.push(el);
    el = el.parentNode;
  }
  return ancestors;
};

const isWhitespace = s => s.trim().length === 0
// =================
// MATCHING CODE
// =================
const initMatch = () => ({
  i: 0,
  lohisByNode: new Map()
})
/** 
 * keeps track of the start (lo) and end (hi) index of the match per node (leaf)
 * note: mutates the contents of `matchContext`
 */
const advanceMatch = (leaf, leafi, matchContext) => {
  matchContext.i++

  const curLoHi = matchContext.lohisByNode.get(leaf)

  matchContext.lohisByNode.set(leaf, { lo: curLoHi?.lo ?? leafi, hi: leafi })
}
/**
 * Finds all non-overlapping matches for a search string in the document. 
 * The search string may be split between multiple consecutive leaf nodes.
 * 
 * Whitespace in the search string must be present in the document to match, but
 * there may be addititional whitespace in the document that is ignored.
 * 
 * e.g. searching for `dogs rock` would match `dogs  \n <span> rock</span>`,
 * and would contribute the match 
 * `{ i:9, els: new Map([[textNode, {lo:0, hi:8}],[spanNode,{lo:0,hi:5}]]) }`
 * 
 * @returns {Map<HTMLElement,{lo:number,hi:number}>[]}
 */
function searchMatches(inSearch, el) {
  // searchText has all sequences of whitespace replaced by a single space
  const searchText = inSearch.toLowerCase().replace(/\s+/g, ' ')
  const leafNodes = getLeafNodes(el)

  /** @type {Map<HTMLElement,{lo:number,hi:number}>[]} */
  const matches = []
  /** @type {{i:number; els:Map<HTMLElement,{lo:number,hi:number}>}[]} */
  let curMatchContext = initMatch()

  for (const leaf of leafNodes) {
    const leafStr = leaf.textContent.toLowerCase()
    // for each character in this leaf's text:
    for (let leafi = 0; leafi < leafStr.length; leafi++) {

      if (isWhitespace(leafStr[leafi])) {
        // if there is at least one whitespace in the document
        // we advance over a search text whitespace.
        if (isWhitespace(searchText[curMatchContext.i])) advanceMatch(leaf, leafi, curMatchContext)
        // all sequences of whitespace are otherwise ignored.
      } else {
        if (searchText[curMatchContext.i] === leafStr[leafi]) {
          advanceMatch(leaf, leafi, curMatchContext)
        } else {
          curMatchContext = initMatch()
          // if current character in the document did not match at i in the search text,
          // reset the search and see if that character matches at 0 in the search text.
          if (searchText[curMatchContext.i] === leafStr[leafi]) advanceMatch(leaf, leafi, curMatchContext)
        }
      }

      const isMatchComplete = curMatchContext.i === searchText.length
      if (isMatchComplete) {
        matches.push(curMatchContext.lohisByNode)
        curMatchContext = initMatch()
      }
    }
  }

  return matches
}

/** 
 * e.g. `markMatches(myTextNode, [[0,5],[12,15]])` would wrap the
 * character sequences in myTextNode from 0-5 and 12-15 in marks.
 * Its important to mark all sequences in a text node at once
 * because this function replaces the entire text node; so any
 * other references to that text node will no longer be in the DOM.
 */
function markMatches(node, lohis) {
  const text = node.nodeValue

  const markFragment = document.createDocumentFragment();

  let prevHi = 0
  for (const [lo, hi] of lohis) {
    markFragment.append(
      document.createTextNode(text.slice(prevHi, lo)),
      markEl(text.slice(lo, hi + 1))
    )
    prevHi = hi + 1
  }
  markFragment.append(
    document.createTextNode(text.slice(prevHi, text.length))
  )

  const parent = node.parentElement
  parent?.replaceChild(markFragment, node)
  return parent
}

// Activate ancestor tabs so a search match inside an inactive pane becomes visible.
// When multiple panes in the same tabset contain matches, avoid switching away from
// the currently active pane — the user already sees a match there.
function openAllTabsetsContainingEl(el) {
  for (const pane of matchAncestors(el, '.tab-pane')) {
    const tabContent = pane.closest('.tab-content');
    if (!tabContent) continue;
    const activePane = tabContent.querySelector(':scope > .tab-pane.active');
    if (activePane?.querySelector('mark')) continue;
    const tabButton = document.querySelector(`[data-bs-target="#${pane.id}"]`);
    if (tabButton) new bootstrap.Tab(tabButton).show();
  }
}

function scrollToFirstVisibleMatch(mainEl) {
  for (const mark of mainEl.querySelectorAll("mark")) {
    const isMarkVisible = matchAncestors(mark, '.tab-pane').every(markTabPane =>
      markTabPane.classList.contains("active")
    )
    if (isMarkVisible) {
      mark.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
  }
}

/**
 * e.g.
 * ```js
 * const m = new Map()
 *
 * arrayMapPush(m, 'dog', 'Max')
 * console.log(m) // Map { dog->['Max'] }
 * 
 * arrayMapPush(m, 'dog', 'Samba')
 * arrayMapPush(m, 'cat', 'Scruffle')
 * console.log(m) // Map { dog->['Max', 'Samba'], cat->['Scruffle'] }
 * ```
 */
const arrayMapPush = (map, key, item) => {
  if (!map.has(key)) map.set(key, [])
  map.set(key, [...map.get(key), item])
}

// copy&paste any string from a quarto page and
// this should find that string in the page and highlight it.
// exception: text that starts outside/inside a tabset and ends
// inside/outside that tabset. 
function highlight(searchStr, el) {
  const matches = searchMatches(searchStr, el);

  const matchesGroupedByNode = new Map()
  for (const match of matches) {
    for (const [mel, { lo, hi }] of match) {
      arrayMapPush(matchesGroupedByNode, mel, [lo, hi])
    }
  }

  for (const [node, lohis] of matchesGroupedByNode) {
    markMatches(node, lohis)
  }
}

/* Link Handling */
// get the offset from this page for a given site root relative url
function offsetURL(url) {
  var offset = getMeta("quarto:offset");
  return offset ? offset + url : url;
}

// read a meta tag value
function getMeta(metaName) {
  var metas = window.document.getElementsByTagName("meta");
  for (let i = 0; i < metas.length; i++) {
    if (metas[i].getAttribute("name") === metaName) {
      return metas[i].getAttribute("content");
    }
  }
  return "";
}

function algoliaSearch(query, limit, algoliaOptions) {
  const { getAlgoliaResults } = window["@algolia/autocomplete-preset-algolia"];

  const applicationId = algoliaOptions["application-id"];
  const searchOnlyApiKey = algoliaOptions["search-only-api-key"];
  const indexName = algoliaOptions["index-name"];
  const indexFields = algoliaOptions["index-fields"];
  const searchClient = window.algoliasearch(applicationId, searchOnlyApiKey);
  const searchParams = algoliaOptions["params"];
  const searchAnalytics = !!algoliaOptions["analytics-events"];

  return getAlgoliaResults({
    searchClient,
    queries: [
      {
        indexName: indexName,
        query,
        params: {
          hitsPerPage: limit,
          clickAnalytics: searchAnalytics,
          ...searchParams,
        },
      },
    ],
    transformResponse: (response) => {
      if (!indexFields) {
        return response.hits.map((hit) => {
          return hit.map((item) => {
            return {
              ...item,
              text: highlightMatch(query, item.text),
            };
          });
        });
      } else {
        const remappedHits = response.hits.map((hit) => {
          return hit.map((item) => {
            const newItem = { ...item };
            ["href", "section", "title", "text", "crumbs"].forEach(
              (keyName) => {
                const mappedName = indexFields[keyName];
                if (
                  mappedName &&
                  item[mappedName] !== undefined &&
                  mappedName !== keyName
                ) {
                  newItem[keyName] = item[mappedName];
                  delete newItem[mappedName];
                }
              }
            );
            newItem.text = highlightMatch(query, newItem.text);
            return newItem;
          });
        });
        return remappedHits;
      }
    },
  });
}

let subSearchTerm = undefined;
let subSearchFuse = undefined;
const kFuseMaxWait = 125;

async function fuseSearch(query, fuse, fuseOptions) {
  let index = fuse;
  // Fuse.js using the Bitap algorithm for text matching which runs in
  // O(nm) time (no matter the structure of the text). In our case this
  // means that long search terms mixed with large index gets very slow
  //
  // This injects a subIndex that will be used once the terms get long enough
  // Usually making this subindex is cheap since there will typically be
  // a subset of results matching the existing query
  if (subSearchFuse !== undefined && query.startsWith(subSearchTerm)) {
    // Use the existing subSearchFuse
    index = subSearchFuse;
  } else if (subSearchFuse !== undefined) {
    // The term changed, discard the existing fuse
    subSearchFuse = undefined;
    subSearchTerm = undefined;
  }

  // Search using the active fuse
  const then = performance.now();
  const resultsRaw = await index.search(query, fuseOptions);
  const now = performance.now();

  const results = resultsRaw.map((result) => {
    const addParam = (url, name, value) => {
      const anchorParts = url.split("#");
      const baseUrl = anchorParts[0];
      const sep = baseUrl.search("\\?") > 0 ? "&" : "?";
      anchorParts[0] = baseUrl + sep + name + "=" + value;
      return anchorParts.join("#");
    };

    return {
      title: result.item.title,
      section: result.item.section,
      href: addParam(result.item.href, kQueryArg, query),
      text: highlightMatch(query, result.item.text),
      crumbs: result.item.crumbs,
    };
  });

  // If we don't have a subfuse and the query is long enough, go ahead
  // and create a subfuse to use for subsequent queries
  if (
    now - then > kFuseMaxWait &&
    subSearchFuse === undefined &&
    resultsRaw.length < fuseOptions.limit
  ) {
    subSearchTerm = query;
    subSearchFuse = new window.Fuse([], kFuseIndexOptions);
    resultsRaw.forEach((rr) => {
      subSearchFuse.add(rr.item);
    });
  }
  return results;
}

/* >>> moondata:offline-search-index —— 由 moondata.docsite 生成，勿手改 */
const __moondataSearchDocuments = [{"objectID": "docs/products.html", "href": "docs/products.html", "title": "产物文档", "section": "", "text": "注记本页每一个数字都来自统计快照\n\n\n\n快照 stats/snapshot.json 生成于 2026-09-23T07:25:37+08:00， 所依据的数据指纹为 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb （数据根下 24,914 个文件，共 956.1 GiB）。 指纹覆盖的是整个数据根（含原始影像），而本页的统计量只来自其中的 patch 产物—— 所以原始影像那边有变动也会让指纹「不一致」，这时本页数字未必真的过期，重扫一次即可确认。\n正文里没有手写的数字：页面渲染时从快照取值，所以移动硬盘没插也照样渲染。 想知道这些数字是否仍然作数，接上盘跑 moondata doctor，看指纹是否「一致」； 不一致就跑 moondata scan 重新生成快照，再 quarto render。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#目录结构", "href": "docs/products.html#目录结构", "title": "产物文档", "section": "目录结构", "text": "目录结构\npatch 产物在数据根下的 Processed_Data/ 里，按划分 → ROI → 模态三层组织：\nProcessed_Data/\n├── Train/\n│   └── ROI_&lt;nnn&gt;/\n│       ├── Optical/   patch_&lt;n&gt;.tif    光学 patch\n│       └── SAR/       patch_&lt;n&gt;.tif    SAR patch\n├── Val/\n│   └── ROI_&lt;nnn&gt;/\n│       ├── Optical/\n│       ├── SAR/\n│       └── Label/     patch_&lt;n&gt;.txt    评测真值点\n│                      patch_&lt;n&gt;.prj    标注软件随手写下的投影文件\n└── Test/              同 Val\n\n划分按 ROI 切，不按 patch 切：同一个 ROI 的全部 patch 落在同一个划分里。\nLabel/ 只出现在Val、Test，训练集没有这一层——见评测真值点覆盖。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#文件命名", "href": "docs/products.html#文件命名", "title": "产物文档", "section": "文件命名", "text": "文件命名\n\nROI 目录名是 ROI_ 加补零到三位的编号（ROI_006）。注意 data/ 下的对齐控制点与 元数据表用的是不补零的写法（ROI_6），两者指同一个 ROI。\npatch_&lt;n&gt; 的 &lt;n&gt; 是该 ROI 内的顺序编号，从零起、不补零，原则上连续（例外见下表）。 同一个 ROI 里，同编号的光学、SAR、标签文件指同一块地面——这是配对的唯一依据， 文件里没有别的配对信息。\n编号不跨 ROI：每个 ROI 都有自己的 patch_0。\n\n扫描时逐一复核了上面这几条：\n\n\n\n检查\n结果\n\n\n\n\n光学与 SAR 编号不成对的 patch\n0 个\n\n\n编号不连续的 ROI\n1 个\n\n\n不符合命名规则的文件\n0 个\n\n\n\n具体是：\n\nTrain/ROI_027", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#数据类型与数值范围", "href": "docs/products.html#数据类型与数值范围", "title": "产物文档", "section": "数据类型与数值范围", "text": "数据类型与数值范围\n两种 patch 都是 512 × 512 像素的 GeoTIFF， 按条带存储、Deflate 压缩，头里带地理参考。\n\n\n\n\n\n\n\n\n\n光学 Optical/\nSAR SAR/\n\n\n\n\n文件数\n9,862\n9,862\n\n\n总大小\n1.2 GiB\n35.8 GiB\n\n\n数据类型\n8 位无符号整型（uint8）\n32 位浮点（float32）\n\n\n波段数\n1\n4\n\n\n尺寸（宽 × 高）\n512 × 512\n512 × 512\n\n\n像素间距\n7.5 m\n7.5 m\n\n\nnodata 值\n0.0\n0.0\n\n\n有效像素的数值范围\n波段 1：1 ~ 255\n波段 1：-0.01426 ~ 9.562波段 2：-0.02231 ~ 10.01波段 3：-3.13 ~ 3.021波段 4：-3.234 ~ 2.74\n\n\nnodata 像素占比\n0.00%\n0.00%\n\n\n含负值的 patch\n0\n9,862\n\n\nNaN 像素\n0\n0\n\n\n\n「有效像素」指不等于 nodata 值的像素；数值范围是在全部 patch 上逐像素取的极值，不是抽样。 nodata 像素占比按「所有波段都等于 nodata」计。\n几点容易踩的：\n\nSAR 含负值是正常的，不是坏数据。9,862 个 SAR patch 里有负值。归一化、取对数之前要先想清楚怎么处理它们。\n光学与 SAR 的像素间距相同，因为两者已被重采样到同一个网格上（见术语表「对齐影像」）。 注意它不是 CE-2 DOM 的原生分辨率——原始光学瓦片与这里的间距不同。\nSAR 各波段的物理含义属于数据来源，见来源文档（尚未产出，issue #7）。\n\n\n怎么读\n\n\n\n\n\n\n警告常见的 Python 影像库读这批 TIFF 会报解压错误\n\n\n\ntifffile（底层是 libdeflate）读它们会报 LIBDEFLATE_BAD_DATA。数据没坏——同一段条带字节 交给标准库 zlib 能完整解出、校验和也对得上，只是 libdeflate 更挑剔。 GDAL/rasterio 读取正常。\n\n\n不想装 GDAL 的话，用本仓库自带的读取器，它只依赖标准库和 numpy：\nfrom moondata.tiff import read_tiff\n\ninfo, optical = read_tiff(\"Processed_Data/Test/ROI_006/Optical/patch_0.tif\")\n_, sar = read_tiff(\"Processed_Data/Test/ROI_006/SAR/patch_0.tif\")\noptical.shape, optical.dtype   # (H, W, 1)  单波段也保留最后一维\nsar.shape, sar.dtype           # (H, W, C)，C 为上表的 SAR 波段数\ninfo.nodata, info.pixel_scale, info.origin", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#划分与数量", "href": "docs/products.html#划分与数量", "title": "产物文档", "section": "划分与数量", "text": "划分与数量\nROI_060 因与另一个 ROI 重复已从数据盘删除（原因见下）， 所以 ROI 与 patch 的数量有两种口径。凡引用数字，都要说明是哪一种。\n\n\n\n\nTrain\nVal\nTest\n合计\n\n\n\n\nROI（现存）\n54\n6\n7\n67\n\n\nROI（含已删除）\n54\n7\n7\n68\n\n\npatch 对（现存）\n7,907\n825\n1,130\n9,862\n\n\npatch 对（含已删除）\n7,907\n977\n1,130\n10,014\n\n\n\n「patch 对」指一张光学 patch 加一张 SAR patch。不指明口径时，本项目说的都是「现存」。\n\n\n\n\n\n\n注记已删除的 ROI_060（原属 Val）\n\n\n\n与 Test/ROI_037 为同一地点(PRODUCT_ID LSZ_01790_2CD_EKU_15S319_V1, CE2 tile H219_10S041W), 152 个光学 patch 中 152 个与 ROI_037 逐像素相同, 造成 Test/Val 不独立。删除于 2026-09-20；删除时它有 152 个 patch 对，其中 145 个带评测真值点。这两个数取自删除时留下的文件清单 data/metadata/removed_ROI_060_manifest.txt——清单只有文件名，所以它的评测真值点点数未知，含已删除口径下的点数一律记为「未知」。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#评测真值点覆盖", "href": "docs/products.html#评测真值点覆盖", "title": "产物文档", "section": "评测真值点覆盖", "text": "评测真值点覆盖\n评测真值点（术语表有专条）是人工在单个 patch 上标注的光学–SAR 同名点，用来评测配准精度。 它只存在于Val、Test，而且不是每个 patch 都有。\n\n\n\n划分\npatch 对\n有真值点的\n覆盖率\n真值点对数\n\n\n\n\nTrain\n7,907\n0\n0.0%\n0\n\n\nVal\n825\n652\n79.0%\n5,289\n\n\nVal（含已删除）\n977\n797\n81.6%\n未知\n\n\nTest\n1,130\n953\n84.3%\n7,742\n\n\n\n\n在Val、Test（现存口径）的 1,955 个 patch 对中， 1,605 个带评测真值点，覆盖率 82.1%。 剩下的 patch 评测时要跳过，不能当作「零误差」或「零个点」参与平均。\n每个带真值点的 patch 上有 7 ~ 11 对点， 中位数 8。\n训练集没有评测真值点：训练集不需要被评测。\n\n\n标签文件格式\nLabel/patch_&lt;n&gt;.txt 是空白分隔的纯文本，每行一对点， 4 列：光学 x、光学 y、SAR x、SAR y，单位是 patch 内像素。\n\n\n\n\n\n\n重要y 坐标取负\n\n\n\n标签文件里的 y 是负的像素行号，与 data/ 下的对齐控制点不同。 扫描复核结果：全部标签文件的 y 列均 ≤ 0，与约定一致。 读的时候取一次负、写的时候再取一次负，中间一律用正的行号。详见术语表「坐标符号约定」。\n\n\n同名的 patch_&lt;n&gt;.prj 是标注软件随标签一起写出的，读标签用不到它。 其中 1,584 个只有一个 GUID 占位、不含投影信息， 21 个写了完整的 WKT 投影， 0 个是别的内容。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#与窗口清单的数量差", "href": "docs/products.html#与窗口清单的数量差", "title": "产物文档", "section": "与窗口清单的数量差", "text": "与窗口清单的数量差\ndata/windows/ 下的窗口清单（windows.json、windows_train.json）逐 ROI 记录了每个 patch 的窗口。 按理它与产物应当一一对应，实际上对不上：\n\n\n\n划分\n清单中的窗口\n清单中的 unresolved\n产物中的 patch 对\n\n\n\n\nTrain\n7,886\n3\n7,907\n\n\nVal\n977\n0\n977\n\n\nTest\n1,130\n0\n1,130\n\n\n\n这里的产物数量按含已删除口径计（清单里仍有 ROI_060）。 清单合计 9,993 个窗口、另有 3 个 unresolved （清单自己承认没能对上的窗口），产物合计 10,014 个 patch 对。 差异全部集中在下面这些 ROI：\n\n\n\nROI\n划分\n清单中的窗口\nunresolved\n产物中的 patch 对\n差\n\n\n\n\nROI_027\nTrain\n234\n3\n234\n+0\n\n\nROI_073\nTrain\n98\n0\n119\n+21\n\n\n\n「产物 − 窗口」合计 +21；若把 unresolved 也算作清单记录过的窗口， 合计 +18——此前口头流传的那个差数是后一种算法。\n这两处差异的来历（据数据集作者说明）：\n\nROI_073：清单里的窗口本身是错的。 该 ROI 最初的对齐控制点有误（见 data/README.md 中 cropped_2 的重标记录），清单里的窗口是按那批错误的点算出来的，与现有产物对不上是 预期之内的。它在训练集，正向复现不要求与这里的旧窗口一致。\nROI_027：unresolved 可能是被删掉的全黑 patch。 作者印象中，当年有几个 patch 因光照原因基本全黑而被删掉，这与该 ROI 的编号断档（见文件命名）吻合。 这一条只是回忆，尚未核实。\n\n正向复现的验收只在验证集与测试集上设门：这两个划分的清单与产物完全对得上。 训练集上的差异不影响验收，也不得为凑数修改窗口清单或产物。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#逐-roi-数量", "href": "docs/products.html#逐-roi-数量", "title": "产物文档", "section": "逐 ROI 数量", "text": "逐 ROI 数量\n\n\n\nROI\n划分\npatch 对\n有真值点的\n真值点对数\n\n\n\n\nROI_001\nTrain\n40\n0\n0\n\n\nROI_002\nTrain\n152\n0\n0\n\n\nROI_003\nTrain\n171\n0\n0\n\n\nROI_005\nTrain\n135\n0\n0\n\n\nROI_006\nTest\n81\n67\n538\n\n\nROI_007\nTest\n372\n286\n2,315\n\n\nROI_008\nTrain\n291\n0\n0\n\n\nROI_009\nTrain\n162\n0\n0\n\n\nROI_010\nTrain\n159\n0\n0\n\n\nROI_011\nTest\n92\n83\n706\n\n\nROI_012\nTrain\n105\n0\n0\n\n\nROI_013\nTrain\n54\n0\n0\n\n\nROI_015\nTrain\n98\n0\n0\n\n\nROI_016\nTrain\n265\n0\n0\n\n\nROI_017\nTrain\n213\n0\n0\n\n\nROI_018\nTrain\n117\n0\n0\n\n\nROI_020\nTest\n112\n91\n739\n\n\nROI_021\nTrain\n108\n0\n0\n\n\nROI_023\nTrain\n175\n0\n0\n\n\nROI_024\nTrain\n239\n0\n0\n\n\nROI_025\nTrain\n222\n0\n0\n\n\nROI_026\nTrain\n190\n0\n0\n\n\nROI_027\nTrain\n234\n0\n0\n\n\nROI_030\nTrain\n74\n0\n0\n\n\nROI_031\nTrain\n149\n0\n0\n\n\nROI_033\nTrain\n269\n0\n0\n\n\nROI_034\nTrain\n199\n0\n0\n\n\nROI_035\nVal\n214\n172\n1,383\n\n\nROI_037\nTest\n159\n141\n1,133\n\n\nROI_038\nTrain\n64\n0\n0\n\n\nROI_042\nTrain\n21\n0\n0\n\n\nROI_043\nTrain\n48\n0\n0\n\n\nROI_045\nTrain\n58\n0\n0\n\n\nROI_046\nTrain\n165\n0\n0\n\n\nROI_047\nTrain\n31\n0\n0\n\n\nROI_048\nTrain\n24\n0\n0\n\n\nROI_049\nVal\n113\n88\n706\n\n\nROI_050\nTrain\n160\n0\n0\n\n\nROI_051\nTrain\n196\n0\n0\n\n\nROI_052\nTrain\n170\n0\n0\n\n\nROI_053\nTrain\n93\n0\n0\n\n\nROI_054\nTest\n168\n145\n1,187\n\n\nROI_055\nTrain\n214\n0\n0\n\n\nROI_056\nTrain\n296\n0\n0\n\n\nROI_057\nTrain\n229\n0\n0\n\n\nROI_058\nTrain\n248\n0\n0\n\n\nROI_059\nTest\n146\n140\n1,124\n\n\nROI_061\nTrain\n97\n0\n0\n\n\nROI_062\nTrain\n136\n0\n0\n\n\nROI_063\nTrain\n103\n0\n0\n\n\nROI_064\nTrain\n111\n0\n0\n\n\nROI_065\nTrain\n172\n0\n0\n\n\nROI_066\nTrain\n130\n0\n0\n\n\nROI_067\nTrain\n120\n0\n0\n\n\nROI_068\nTrain\n107\n0\n0\n\n\nROI_069\nTrain\n198\n0\n0\n\n\nROI_070\nVal\n168\n113\n910\n\n\nROI_071\nVal\n40\n30\n241\n\n\nROI_072\nTrain\n60\n0\n0\n\n\nROI_073\nTrain\n119\n0\n0\n\n\nROI_074\nTrain\n141\n0\n0\n\n\nROI_075\nVal\n183\n174\n1,442\n\n\nROI_076\nTrain\n58\n0\n0\n\n\nROI_077\nTrain\n165\n0\n0\n\n\nROI_078\nTrain\n167\n0\n0\n\n\nROI_079\nTrain\n185\n0\n0\n\n\nROI_080\nVal\n107\n75\n607", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "CONTEXT.html", "href": "CONTEXT.html", "title": "术语表", "section": "", "text": "本文件是本项目的词汇表：每条只给定义与中英对照，不讲实现、不给操作步骤、 不放统计数字。要知道数据从哪来、怎么被做成这样、最终长什么样，看主体文档。\n词汇表放在仓库根而不是只放在文档站里，是因为它同时服务两类读者：读文档站的人， 以及只有一个终端、正要动手改代码的人（含 agent）。两边看到的是同一份文件—— 文档站里的这一页就是 CONTEXT.md 本身渲染出来的，不存在第二份会漂的副本。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#影像与区域", "href": "CONTEXT.html#影像与区域", "title": "术语表", "section": "影像与区域", "text": "影像与区域\n\nROI（region of interest，感兴趣区）\n一块光学与 SAR 同时覆盖的月表区域，是本数据集的组织单位。编号形如 ROI_35。 每个 ROI 有自己的一对对齐影像、一套对齐控制点、一批 patch。\n\n\n光学影像（optical image）\n嫦娥二号（CE-2）7 m 分辨率数字正射影像（DOM）。单波段，8 位无符号整型。\n\n\nSAR 影像（SAR image）\nMini-RF 雷达影像。四波段，32 位浮点，含负值。\n\n\n对齐影像（aligned image）\n一个 ROI 的光学与 SAR 被重采样到同一网格后的那一对大图。patch 从它上面切出来， 对齐控制点也标在它上面。\n\n\npatch（切片）\n从对齐影像上按固定尺寸切下来的小图，光学与 SAR 一一对应，同编号即同一块地面。 它是数据集对外交付的最小单位，也是评测真值点唯一存在的地方。 中文里不译，沿用 patch——既有代码、目录名与文件名全都是这个词。\n\n\n划分（split）\nTrain / Val / Test，按 ROI 划分，不按 patch 划分：同一个 ROI 的全部 patch 落在同一个划分里。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#两种同名点这两条必须分清", "href": "CONTEXT.html#两种同名点这两条必须分清", "title": "术语表", "section": "两种同名点（这两条必须分清）", "text": "两种同名点（这两条必须分清）\n「同名点」（tie point / corresponding point）指一对指向同一地物的坐标——一个在光学上， 一个在 SAR 上。本项目里有两批同名点，它们的标注位置、数量级、覆盖范围和用途 完全不同，混用会直接导致错误结论。\n\n对齐控制点（alignment tie points）\n\n标在哪 —— 人工在 ENVI 中于对齐影像（整幅大图）上标注。\n多少 —— 每个 ROI 约 30 对。\n覆盖 —— 全部 67 个 ROI，三个划分都有。\n用途 —— 求解该 ROI 的全局变换，进而决定 patch 切在哪。它是生产资料。\n不是什么 —— 不是评测的金标准。拿它去评测，等于用造数据的那把尺子量数据自己。\n\n\n\n评测真值点（evaluation ground truth）\n\n标在哪 —— 人工在单个 patch 上标注。\n多少 —— 每个 patch 约 8 对。\n覆盖 —— 只存在于验证集与测试集，且只覆盖其中约 82% 的 patch； 训练集完全没有。\n用途 —— 评测配准算法的精度。它是评测基准。\n\n\n\n为什么按用途命名\n这两批点在既有代码与文件名里被叫作 tie 和 label，口头上则常被称作「大图上的点」 与「小图上的点」。文档一律使用上面两个专名，因为按位置命名解释不了 「训练集为什么没有后者」，而按用途命名，答案自明：训练集不需要被评测。\n文件名与文件格式保持现状不改——它们是格式契约，既有数据和既有代码都按它读写。 改的只是我们讲话时用的词。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#坐标符号约定coordinate-sign-convention", "href": "CONTEXT.html#坐标符号约定coordinate-sign-convention", "title": "术语表", "section": "坐标符号约定（coordinate sign convention）", "text": "坐标符号约定（coordinate sign convention）\n\n\n\n\n\n\n重要弄错了不会报错，只会算出镜像的结果\n\n\n\n三种同名点文件对 y 的符号处理不一致，而三者都是纯文本的数字列。取错符号的产物 在数值上完全正常、打开看也完全正常，只有配准结果整体沿水平轴翻转——没有任何一步 会抛异常。这是本项目最容易静默出错的地方，所以它被钉进词汇表。\n\n\n\n\n\n文件\n内容\n坐标\ny 的符号\n\n\n\n\nLabel/patch_&lt;n&gt;.txt\n评测真值点\npatch 内像素\n取负\n\n\ncropped/opt_tie.pts\n对齐控制点\n对齐影像像素\n不取负\n\n\ncropped/opt_tie.txt\n对齐控制点\n地图坐标（米）\n不取负\n\n\n\n约定：包内一律用不取负的 y（向下为正的像素行号），取负只是标签文件的磁盘格式。 因此符号转换只发生在读写边界——读标签文件时取一次负，写标签文件时再取一次负， 中间所有计算、所有内存中的数组，y 都是正的。任何在中途翻符号的代码都是错的。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#复现与验收", "href": "CONTEXT.html#复现与验收", "title": "术语表", "section": "复现与验收", "text": "复现与验收\n\n窗口（window）\n一个 patch 在对齐影像上的位置，记作左上角像素坐标加固定的 patch 尺寸。 「算窗口」与「切 patch」是两件事：前者不读影像，后者要。\n\n\n窗口清单（window manifest）\ndata/windows/ 下逐 ROI 记录网格与全部窗口坐标的 JSON。\n它的用途发生过一次转变：最初是从已有 patch 反推出来的，为的是重切之后 「网格、窗口、编号」三者不变，从而让 patch 上的评测真值点继续成立；现在它是 正向复现的验收基准——新代码正向算出的窗口必须与它逐条相等。同一份文件， 两种截然不同的用途。\n\n\n正向复现（forward reproduction）\n从原始输入与对齐控制点独立算出现有数据集，不读取任何历史产物的位置信息。 这是本项目对代码的核心要求，也是「第二版代码读着旧 patch 反推着切」这一做法被废弃的原因。\n\n\n一级验收 / 二级验收（level-1 / level-2 acceptance）\n\n一级：正向算出的窗口与窗口清单逐条相等。不读影像，快。\n二级：切出的 patch 与现有产物逐字节一致。要读影像，慢。\n\n\n\n冻结（frozen）\n验证集与测试集不再重切。原因是人工标注的评测真值点会随重切而作废， 不是数据本身有问题。训练集不受这条约束——它没有评测真值点，没有什么会作废。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#工作区", "href": "CONTEXT.html#工作区", "title": "术语表", "section": "工作区", "text": "工作区\n\n数据根（data root）\n955 GB 影像所在目录的本机路径。影像不进仓库，靠它引用；不同机器挂载点不同， 所以它可配置（--data-root → MOONDATA_DATA_ROOT → moondata.toml，取第一个非空的）。\n\n\n统计快照（statistics snapshot）\nstats/snapshot.json。从真实数据扫描出来的统计量，携带生成时间与一枚数据指纹。 文档只读快照，不读影像——所以移动硬盘没插时文档照样渲染。\n\n\n删除清单（removal manifest）\n删除某个 ROI 的 patch 产物时留下的文件清单：写明删了什么、为什么、何时删，并逐行列出 被删文件的相对路径。它是被删 ROI 唯一的剩余记录，统计「含已删除 ROI」口径的数量 全靠它。目前只有一份：ROI_60（与 ROI_37 逐像素重复）。\n\n\n数据指纹（data fingerprint）\n刻画数据根目录形态（相对路径 + 文件大小）的摘要，不是像素内容的哈希。 它回答的是「快照还作不作数」。", "crumbs": ["首页", "术语表"]}, {"objectID": "index.html", "href": "index.html", "title": "月球光学–SAR 配准数据集", "section": "", "text": "这里是这个数据集的全部说明材料。数据集已经冻结，955 GB 影像不在仓库里； 这个站点要回答的是：它是什么、从哪来、怎么被做成这样、以及你拿到的是什么。", "crumbs": ["首页"]}, {"objectID": "index.html#怎么读", "href": "index.html#怎么读", "title": "月球光学–SAR 配准数据集", "section": "怎么读", "text": "怎么读\n什么都不用装。 站点的构建产物随仓库一起提交，克隆下来双击 _site/index.html 就能看——不需要 Python、不需要 Quarto、不需要联网，也不需要接那块移动硬盘。\n左边是导航树，右边是本页目录，右上角的搜索框搜全站正文（中文可用）。\n\n\n\n\n\n\n提示第一次来，先读术语表\n\n\n\n尤其是对齐控制点与评测真值点的区别，以及坐标符号约定。 前者错了会让评测结论失效，后者错了会让配准结果整体镜像——而且两种错误都不报错。", "crumbs": ["首页"]}, {"objectID": "index.html#数据集是怎么来的", "href": "index.html#数据集是怎么来的", "title": "月球光学–SAR 配准数据集", "section": "数据集是怎么来的", "text": "数据集是怎么来的\n\n\n\n\n\nflowchart LR\n  A[\"① 算重叠区&lt;br/&gt;光学 ∩ SAR\"] --&gt; B[\"② 标对齐控制点&lt;br/&gt;人工，ENVI\"]\n  B --&gt; C[\"③ 估计全局变换&lt;br/&gt;每 ROI 一个\"]\n  C --&gt; D[\"④ 正向算窗口&lt;br/&gt;切 patch\"]\n  B -.-&gt; E[[\"不可再生&lt;br/&gt;已入库 data/\"]]\n  D --&gt; F[\"数据集&lt;br/&gt;67 个 ROI\"]\n\n\n\n\n\n\n第 ② 步是人工的，无法自动复现，所以那批标注被当作数据纳入版本控制 （仓库里的 data/README.md）。 其余三步要求正向计算：不读任何历史产物的位置信息，独立算出与现有数据集一致的结果。\n代码的顶层模块与这四步一一对应，所以目录结构本身就是上面这张图。", "crumbs": ["首页"]}, {"objectID": "index.html#站点里有什么", "href": "index.html#站点里有什么", "title": "月球光学–SAR 配准数据集", "section": "站点里有什么", "text": "站点里有什么\n\n\n\n\n内容\n状态\n\n\n\n\n术语表\n词汇与坐标符号约定\n本轮产出\n\n\n来源文档\n数据从哪来：官方产品、投影、波段\n尚未产出（issue #7）\n\n\n流程文档\n它如何被做成这样\n尚未产出（issue #11）\n\n\n产物文档\n你拿到的是什么：目录、命名、类型、数量、真值点覆盖\n已产出\n\n\n数据集特性研究\n一个问题一篇的研究笔记\n本轮不产出，仅留位\n\n\n\n文档里的统计数字都从统计快照取值，不手写——快照由 moondata scan 从真实数据扫描生成， 随仓库提交，所以数字不会在无人察觉时过期，移动硬盘没插时文档也照样渲染。", "crumbs": ["首页"]}, {"objectID": "index.html#怎么重新构建", "href": "index.html#怎么重新构建", "title": "月球光学–SAR 配准数据集", "section": "怎么重新构建", "text": "怎么重新构建\nquarto render\n一条命令，产出提交到 _site/。改完 .qmd 记得重跑一次，否则读者看到的还是旧的。", "crumbs": ["首页"]}, {"objectID": "docs/dataset-study.html", "href": "docs/dataset-study.html", "title": "数据集特性研究", "section": "", "text": "注记这一部分现在是空的，而且是有意空着的\n\n\n\n本轮（issue #4）只在导航里为它留一个位置，不产出任何内容。 下面写的是将来往这里放什么、以什么形式放，不是结论。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "docs/dataset-study.html#将来放什么", "href": "docs/dataset-study.html#将来放什么", "title": "数据集特性研究", "section": "将来放什么", "text": "将来放什么\n数据集本身的性质问题——不是「它怎么被做出来的」（那是流程文档），而是 「它是什么样的、有什么毛病、某个现象为什么会这样」。已经知道存在、但本轮明确不碰的， 例如：若干 ROI 的局部错位、若干 ROI 的 SAR 距离向有效分辨率异常、 窗口清单与实际产物的数量差、部分 ROI 是否残留旧的重采样网纹。\n人工标注的质量至今没有评估过。这是将来必做的一项，本轮完全不碰—— 在它做完之前，任何基于评测真值点得出的精度数字都建立在一个未经检验的前提上。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "docs/dataset-study.html#以什么形式放", "href": "docs/dataset-study.html#以什么形式放", "title": "数据集特性研究", "section": "以什么形式放", "text": "以什么形式放\n一个问题一篇，笔记式，不预先搭章节结构。每篇包含问题、证据、结论， 并且保留已经被证伪的假设：走过的死路和它为什么是死路，与结论同样值得写下来， 否则接手的人会把同一条路再走一遍。\n之所以不在这里先摆出一排空标题，是因为章节结构会反过来规定研究该往哪走。 等真有了第一篇再谈结构。\n笔记可以是 .qmd，也可以直接是 .ipynb——Quarto 两种都能渲染成站点的一页， 不需要为此改工具链。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}];
function __moondataOfflineSearchResponse() {
  return {
    status: 200,
    json: function () {
      return Promise.resolve(__moondataSearchDocuments);
    },
  };
}
/* <<< moondata:offline-search-index */
